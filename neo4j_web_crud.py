"""Neo4j CRUD Web 应用。

保留原有 HTTP 接口和返回结构，仅整理配置、事务调用、序列化与错误处理。
"""

import logging
import os
from uuid import uuid4

from flask import Flask, jsonify, render_template, request
from neo4j import GraphDatabase
from neo4j.exceptions import ServiceUnavailable
from dotenv import load_dotenv


load_dotenv()
app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 连接信息从环境变量读取，避免将数据库密码提交到代码仓库。
NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD")
if not NEO4J_PASSWORD:
    raise RuntimeError("请在 .env 文件中设置 NEO4J_PASSWORD")
driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))


def escape_identifier(value):
    """安全引用 Cypher 标签、关系类型和属性名。"""
    if not isinstance(value, str) or not value.strip():
        raise ValueError("标识符不能为空")
    return f"`{value.strip().replace('`', '``')}`"


def node_labels(node):
    """兼容不同 Neo4j 驱动版本的节点标签读取方式。"""
    return list(node.labels) if hasattr(node, "labels") else []


def node_to_dict(node, fallback_label="Node"):
    labels = node_labels(node)
    return {
        "id": node.id,
        "properties": dict(node),
        "label": labels[0] if labels else fallback_label,
    }


def run_read(session, callback, *args, **kwargs):
    executor = getattr(session, "execute_read", None) or session.read_transaction
    return executor(callback, *args, **kwargs)


def run_write(session, callback, *args, **kwargs):
    executor = getattr(session, "execute_write", None) or session.write_transaction
    return executor(callback, *args, **kwargs)


def json_body(required_fields):
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return None, (jsonify({"error": "请求数据必须是 JSON 对象"}), 400)

    missing = [field for field in required_fields if field not in data]
    if missing:
        return None, (
            jsonify({"error": f"请求缺少必要字段：{', '.join(missing)}"}),
            400,
        )
    return data, None


def database_unavailable_response():
    return jsonify({"error": "无法连接到 Neo4j 数据库"}), 503


def create_node(tx, label, properties):
    properties = dict(properties)
    properties.setdefault("id", str(uuid4())[:8])
    query = f"CREATE (n:{escape_identifier(label)} $props) RETURN n"
    record = tx.run(query, props=properties).single()
    return record["n"] if record else None


def read_nodes(tx, label=None):
    label_clause = f":{escape_identifier(label)}" if label else ""
    return [record["n"] for record in tx.run(f"MATCH (n{label_clause}) RETURN n")]


def get_node_by_id(tx, node_id):
    record = tx.run(
        "MATCH (n) WHERE id(n) = $id RETURN n", id=node_id
    ).single()
    return record["n"] if record else None


def get_related_nodes(tx, node_id):
    query = """
        MATCH (n)-[r]->(m) WHERE id(n) = $id
        RETURN r, m, 'outgoing' AS direction
        UNION
        MATCH (m)-[r]->(n) WHERE id(n) = $id
        RETURN r, m, 'incoming' AS direction
    """
    related = []
    for record in tx.run(query, id=node_id):
        relationship = record["r"]
        related_node = record["m"]
        labels = node_labels(related_node)
        related.append(
            {
                "relationship": {
                    "id": relationship.id,
                    "type": relationship.type,
                    "properties": dict(relationship),
                    "direction": record["direction"],
                },
                "node": {
                    "id": related_node.id,
                    "properties": dict(related_node),
                    "labels": labels[0] if labels else "Node",
                },
            }
        )
    return related


def update_node(tx, label, old_properties, new_properties):
    old_parts = []
    new_parts = []
    params = {}

    for index, (key, value) in enumerate(old_properties.items()):
        param = f"old_{index}"
        old_parts.append(f"n.{escape_identifier(key)} = ${param}")
        params[param] = value

    for index, (key, value) in enumerate(new_properties.items()):
        param = f"new_{index}"
        new_parts.append(f"n.{escape_identifier(key)} = ${param}")
        params[param] = value

    query = (
        f"MATCH (n:{escape_identifier(label)}) "
        f"WHERE {' AND '.join(old_parts)} "
        f"SET {', '.join(new_parts)} RETURN n"
    )
    record = tx.run(query, params).single()
    return record["n"] if record else None


def delete_node(tx, label, properties):
    query = f"MATCH (n:{escape_identifier(label)} $props) DETACH DELETE n"
    tx.run(query, props=properties).consume()
    return True


def create_relationship(
    tx, start_label, start_props, end_label, end_props, rel_type, rel_props=None
):
    start_where = []
    end_where = []
    params = {"rel_props": rel_props or {}}

    for index, (key, value) in enumerate(start_props.items()):
        param = f"start_{index}"
        start_where.append(f"n.{escape_identifier(key)} = ${param}")
        params[param] = value

    for index, (key, value) in enumerate(end_props.items()):
        param = f"end_{index}"
        end_where.append(f"m.{escape_identifier(key)} = ${param}")
        params[param] = value

    set_clause = "SET r = $rel_props" if rel_props else ""
    query = f"""
        MATCH (n:{escape_identifier(start_label)})
        WHERE {' AND '.join(start_where)}
        MATCH (m:{escape_identifier(end_label)})
        WHERE {' AND '.join(end_where)}
        CREATE (n)-[r:{escape_identifier(rel_type.upper())}]->(m)
        {set_clause}
        RETURN n AS start_node, m AS end_node, r AS relationship,
               id(n) AS start_id, id(m) AS end_id
    """
    record = tx.run(query, params).single()
    if not record:
        return None

    relationship = record["relationship"]
    return {
        "start_node": dict(record["start_node"]),
        "end_node": dict(record["end_node"]),
        "start_id": record["start_id"],
        "end_id": record["end_id"],
        "relationship": {
            "type": relationship.type,
            "properties": dict(relationship),
        },
    }


def get_statistics(tx):
    return {
        "total_nodes": tx.run("MATCH (n) RETURN count(n) AS count").single()["count"],
        "total_relationships": tx.run(
            "MATCH ()-[r]->() RETURN count(r) AS count"
        ).single()["count"],
        "label_count": len(tx.run("CALL db.labels()").data()),
    }


def get_all_labels_with_counts(tx):
    labels = [record["label"] for record in tx.run("CALL db.labels()")]
    return [
        {
            "label": label,
            "count": tx.run(
                f"MATCH (n:{escape_identifier(label)}) RETURN count(n) AS count"
            ).single()["count"],
        }
        for label in labels
    ]


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/statistics", methods=["GET"])
def statistics():
    try:
        with driver.session() as session:
            return jsonify(run_read(session, get_statistics))
    except ServiceUnavailable:
        return database_unavailable_response()


@app.route("/labels", methods=["GET"])
def labels_list():
    try:
        with driver.session() as session:
            return jsonify({"labels": run_read(session, get_all_labels_with_counts)})
    except ServiceUnavailable:
        return database_unavailable_response()


@app.route("/create", methods=["POST"])
def create():
    data, error = json_body(("label", "properties"))
    if error:
        return error
    if not isinstance(data["properties"], dict):
        return jsonify({"error": "节点属性必须是 JSON 对象"}), 400

    try:
        with driver.session() as session:
            node = run_write(session, create_node, data["label"], data["properties"])
        if not node:
            return jsonify({"error": "创建节点失败"}), 500
        return jsonify(node_to_dict(node, data["label"]))
    except ServiceUnavailable:
        return database_unavailable_response()


@app.route("/read", methods=["GET"])
def read():
    label = request.args.get("label")
    try:
        with driver.session() as session:
            nodes = run_read(session, read_nodes, label)
        return jsonify([node_to_dict(node) for node in nodes])
    except ServiceUnavailable:
        return database_unavailable_response()


@app.route("/node/<int:node_id>/related", methods=["GET"])
def get_related(node_id):
    try:
        with driver.session() as session:
            node = run_read(session, get_node_by_id, node_id)
            if not node:
                return jsonify({"error": "节点不存在"}), 404
            related = run_read(session, get_related_nodes, node_id)
        return jsonify({"node": node_to_dict(node), "related": related})
    except ServiceUnavailable:
        return database_unavailable_response()


@app.route("/update", methods=["PUT"])
def update():
    data, error = json_body(("label", "old_properties", "new_properties"))
    if error:
        return error
    old_properties = data["old_properties"]
    new_properties = data["new_properties"]
    if not isinstance(old_properties, dict) or not old_properties:
        return jsonify({"error": "匹配条件必须是非空 JSON 对象"}), 400
    if not isinstance(new_properties, dict) or not new_properties:
        return jsonify({"error": "更新值必须是非空 JSON 对象"}), 400

    try:
        with driver.session() as session:
            node = run_write(
                session, update_node, data["label"], old_properties, new_properties
            )
        if not node:
            return jsonify({"error": "更新节点失败，可能节点不存在"}), 500
        return jsonify(dict(node))
    except ServiceUnavailable:
        return database_unavailable_response()


@app.route("/delete", methods=["DELETE"])
def delete():
    data, error = json_body(("label", "properties"))
    if error:
        return error
    if not isinstance(data["properties"], dict):
        return jsonify({"error": "匹配条件必须是 JSON 对象"}), 400

    try:
        with driver.session() as session:
            success = run_write(session, delete_node, data["label"], data["properties"])
        if success:
            return jsonify({"message": "节点删除成功"})
        return jsonify({"error": "删除节点失败"}), 500
    except ServiceUnavailable:
        return database_unavailable_response()


@app.route("/create-relationship", methods=["POST"])
def create_relationship_api():
    required = (
        "start_label",
        "start_properties",
        "end_label",
        "end_properties",
        "relationship_type",
    )
    data, error = json_body(required)
    if error:
        return error

    start_props = data["start_properties"]
    end_props = data["end_properties"]
    rel_props = data.get("relationship_properties", {})
    if not isinstance(start_props, dict) or not start_props:
        return jsonify({"error": "起始节点属性必须是非空 JSON 对象"}), 400
    if not isinstance(end_props, dict) or not end_props:
        return jsonify({"error": "结束节点属性必须是非空 JSON 对象"}), 400
    if not isinstance(rel_props, dict):
        return jsonify({"error": "关系属性必须是 JSON 对象（可选）"}), 400

    try:
        with driver.session() as session:
            relationship = run_write(
                session,
                create_relationship,
                data["start_label"],
                start_props,
                data["end_label"],
                end_props,
                data["relationship_type"],
                rel_props,
            )
        if relationship:
            return jsonify(relationship)
        return jsonify({"error": "创建关系失败，未找到匹配的起始/结束节点"}), 500
    except ServiceUnavailable:
        return database_unavailable_response()


if __name__ == "__main__":
    app.run(debug=os.getenv("FLASK_DEBUG", "1") == "1")
