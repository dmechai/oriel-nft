<h1 align="center">Oriel NFT</h1>
<p align="center">面向非设计师的 AI 藏品创作项目。从一张参考图出发，挑选艺术方向，锁定主图，再生成风格一致的 NFT 系列。</p>
<p align="center">
  <img alt="Python" src="https://img.shields.io/badge/Python-3.14-315f98?style=flat-square">
  <img alt="License" src="https://img.shields.io/badge/license-MIT-f97316?style=flat-square">
</p>
<p align="center"><a href="#quick-start">快速开始</a> · <a href="#workflow">使用流程</a> · <a href="#providers">接口</a> · <a href="#docker">Docker</a> · <a href="README.en.md">English</a></p>

Oriel NFT 不提供模型、账号或额度。自行部署时，项目和图片默认留在你自己的机器上，开发者不转发 API 请求，也不承担调用费用。

> 应用本身没有用户登录或租户隔离。默认仅监听本机，适合本地或可信内网使用。不要将应用端口直接暴露到公网。若运营在线实例，必须在反向代理前强制使用 Cloudflare Access、VPN 或等效认证；身份保护不会由这个应用自动提供。公开演示应使用独立、可重置且不保存用户密钥的环境。

## 快速开始

需要 Python 3.12 以上和 Node.js 22。

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cd web && npm ci && npm run build && cd ..
python -m server
```

打开 `http://127.0.0.1:8787`。没有接口时，可以先打开「离线样例」走通属性、合成、稀有度和导出。样例图层是程序绘制的，不是模型生成的。

在线自用实例部署于 `https://oriel.dmechai.com`，并由反向代理身份验证保护；应用本身不是面向匿名公网的多用户服务。

开发界面热更新：

```bash
python -m server
cd web && npm run dev
```

界面开发地址是 `http://127.0.0.1:5173`，接口请求会转到 `8787`。

## 使用流程

1. 新建系列，选择主体改动档位。说明就在选项旁边。
2. 上传参考图。图可以是角色、静物、照片或抽象图，分析后再决定怎么做。
3. 生成三张明显不同的方向图，用一句话精修，然后锁定一张主图。
4. 确认风格合同，规划属性。背景、局部补丁和配件可以分层，衣服、姿势等结构变化用整体基底。锁定后，如需换主图，请新建系列。
5. 生成素材并逐项通过。修改风格合同后，请重新审核素材。改动属性描述、图层方式或位置后，请为该属性重新生成素材。
6. 在「系列」点击「试生成样张」，查看最多 8 张预览。确认主体、光照和图层边缘后，点击「确认样张」，再正式生成。变更素材、规则或主体分离图后，需要重新确认。
7. 分页浏览成品，重做单张或编辑属性，再下载 ZIP。包内有 `images/` 下的 PNG、`metadata/` 下逐张对应的 JSON，以及 `summary/` 下的稀有度统计和清单。

正式出图按权重选取合法组合，并用已审核图层合成。合法组合不足或发现像素完全相同的成品时，整批生成会停止，已有系列仍可下载。视觉接近的图片会标记供你检查。

上链、钱包和交易市场不在这一版里。导出的 metadata 可以以后交给你自己的发布流程。

## 接口

在「接口设置」填写：

- Base URL：OpenAI 兼容地址，通常以 `/v1` 结尾。
- API Key 可选。本地服务如果无需身份验证，可以留空。已保存的密钥用本机 `data/secret.key` 加密，界面只显示保存状态。更换 Base URL 时，请填写新地址对应的密钥。
- 视觉、规划、图像生成和参考图编辑可分别选模型。参考图编辑模型留空时沿用图像生成模型。
- 出图方式可选 OpenAI Images 接口，或支持接收并返回图像的对话接口。

可以通过 `/models` 下拉选择，也可以手动填写。严格保留模式、语言精修、模型分离主体和生成素材都需要参考图编辑。其余方向探索在编辑端点不可用时可以退回文字出图，界面会标注该方向是否发送了参考图。远程调用时，图片会发送到所选接口，调用费用由该服务计收。

## 技能

`skills/*.json` 是内置技能。每个技能必须写明一致性约束、三种锁定前的方向，以及哪些属性可以分层、哪些只能整图重绘。系列一旦锁定主图，就只遵守这一份风格合同，不能把三张方向图混进同一套。

社区技能沿用同一份字段。缺一致性约束的文件不会被加载。

## Docker

```bash
docker compose up --build
```

数据卷是 `oriel-data`，里面有数据库、图片和 `secret.key`。丢失 `secret.key` 后，已保存的 API Key 无法解密，需要重新填写。容器内监听 `0.0.0.0:8787`，映射到宿主的 `127.0.0.1:8787`。不要将容器端口直接公开；在线运行前须在反向代理或 Cloudflare Access 上启用身份验证。

## 测试

```bash
pip install -r requirements.txt
pytest
```

测试覆盖组合不足、绿幕抠图、样张门禁、失败时保留已有系列、参考图编辑的回退条件、密钥回传检查，以及 100 张离线样例的 PNG、Metadata 和统计文件校验。

## 数据

默认数据目录是项目下的 `data/`，可用 `ORIEL_DATA` 改到别的位置。导出 ZIP 只包含图片、metadata、稀有度统计和一份不含密钥的 manifest。

界面使用 Fraunces 和 Outfit，授权文本保存在 `web/public/fonts/`。
