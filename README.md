# 同词相遇 Sameet

一个无需注册的双人实时联想猜词网页游戏。房主创建房间并分享链接，两位玩家每轮各自提交一个词，答案同时揭晓；如果不同，就根据这两个词继续联想，直到两人的答案相同。

## 本地运行

```powershell
cd "D:\学习记录\sameet"
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m uvicorn app:app --reload
```

如果 PyPI 下载较慢，可以改用清华镜像：

```powershell
pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt
```

打开 <http://127.0.0.1:8000>。同一局可以用两个浏览器或一个普通窗口加一个无痕窗口测试。

## 当前能力

- 无需注册，昵称保存在当前浏览器
- 6 位房间码与邀请链接
- 30 秒、60 秒或 10～300 秒自定义时长
- WebSocket 实时同步玩家、提交、揭晓和掉线状态
- 服务端计时；超时后暂停等待，仍可提交
- 提交后不可修改且不会提前泄露答案
- 自动规范首尾空格、连续空格和英文大小写
- 断线自动重连、刷新恢复身份
- 完整词语轨迹、结算与再来一局
- 响应式手机布局

## 项目结构

```text
app.py                 FastAPI API、WebSocket 与房间状态机
static/index.html       首页
static/room.html        房间与游戏页
static/styles.css       响应式样式
static/app.js           首页交互
static/room.js          实时游戏交互
```

房间目前保存在内存中，服务重启后会清空；无人连接的房间会在 30 分钟后自动清理。这一实现适合快速验证产品。正式上线并运行多个服务进程时，应把房间状态和消息广播迁移到 Redis，并在反向代理中开启 WebSocket 支持。

