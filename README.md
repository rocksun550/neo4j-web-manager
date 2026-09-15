# Neo4j Web Manager

一个基于 Flask 和 Neo4j 的轻量级图数据库管理界面，支持节点和关系的常用操作，并提供可交互的图谱可视化。

展示
<img width="1912" height="902" alt="image" src="https://github.com/user-attachments/assets/0667de2c-b38a-41a7-8017-058434fe1c2b" />
<img width="1392" height="667" alt="image" src="https://github.com/user-attachments/assets/09a75909-4c6c-40ec-8349-61d1dcd9d6b5" />

## 功能

- 查看节点、关系和标签统计信息
- 创建、查询、更新和删除节点
- 创建两个已有节点之间的关系
- 按标签加载节点
- 单击节点或关系查看属性
- 双击节点加载关联节点和关系
- 拖动节点调整图谱布局
- 响应式界面，支持桌面和移动端

## 项目结构

```text
neo4j-web-manager/
├── neo4j_web_crud.py       # Flask 后端及 Neo4j 操作
├── templates/
│   └── index.html          # Web 管理界面
├── .env.example            # 环境变量示例
├── .gitignore
├── requirements.txt
└── README.md
```

## 运行条件

- Python 3.9 或更高版本
- Neo4j 数据库
- 可访问的 Bolt 连接地址，默认是 `bolt://localhost:7687`

## 安装与运行

### 1. 创建虚拟环境

Windows PowerShell：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

macOS 或 Linux：

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

### 3. 配置 Neo4j

复制 `.env.example` 并重命名为 `.env`：

```env
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=你的数据库密码
FLASK_DEBUG=1
```

`.env` 已加入 `.gitignore`，不会被 Git 提交。请勿把真实密码写入代码或 `.env.example`。

### 4. 启动应用

```bash
python neo4j_web_crud.py
```

浏览器访问：

```text
http://127.0.0.1:5000
```

## API 概览

| 方法 | 地址 | 作用 |
| --- | --- | --- |
| `GET` | `/statistics` | 获取节点、关系及标签统计 |
| `GET` | `/labels` | 获取所有标签及节点数量 |
| `POST` | `/create` | 创建节点 |
| `GET` | `/read` | 查询节点 |
| `GET` | `/node/<id>/related` | 查询节点及其关联数据 |
| `PUT` | `/update` | 更新节点属性 |
| `DELETE` | `/delete` | 删除节点及其关系 |
| `POST` | `/create-relationship` | 创建节点关系 |


