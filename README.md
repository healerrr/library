# 文鉴 CopyGuard

用于采集多个网站的有效文案，并在新网站上线前执行整站重复与相似度检测。

## Docker 一键部署

服务器建议配置：2 核 CPU、4 GB 内存、5 GB 以上可用磁盘。首次启动需要联网下载中文语义模型。

需要提前安装：

- Docker Engine 24 或更高版本
- Docker Compose v2 插件

在 Linux 服务器执行：

```bash
git clone https://github.com/healerrr/library.git
cd library
bash deploy.sh
```

脚本会自动完成以下工作：

- 从 `.env.example` 创建 `.env`
- 生成随机 PostgreSQL 密码
- 构建前后端镜像
- 创建 PostgreSQL 与模型持久化卷
- 执行全部 Alembic 数据库迁移
- 下载并缓存 FastEmbed 中文模型
- 等待数据库、后端和前端健康后返回

默认访问地址为 `http://服务器IP:3000`。只有前端入口会暴露到宿主机，浏览器通过同源 `/api` 访问内部后端，PostgreSQL 和后端端口不会直接暴露。

### 域名和反向代理

如果使用 Nginx、Caddy 或云平台反向代理，将 `.env` 中的监听地址改为：

```dotenv
APP_BIND=127.0.0.1
APP_PORT=3000
```

然后把域名代理到 `http://127.0.0.1:3000`，并在代理层配置 HTTPS。

当前应用没有登录鉴权。不要把它无保护地暴露到公网，建议仅在可信内网使用，或在反向代理层增加 Basic Auth、单点登录或访问白名单。

### 常用维护命令

```bash
# 查看状态
docker compose ps

# 查看日志
docker compose logs -f

# 更新代码并重新部署
git pull
bash deploy.sh

# 停止服务（保留数据库和模型）
docker compose down
```

不要使用 `docker compose down -v`，该命令会删除数据库与模型缓存卷。

### 数据库备份

```bash
docker compose exec -T db pg_dump -U copyguard copyguard > copyguard-backup.sql
```

`.env`、数据库卷和模型缓存都不会提交到 Git。
