# 第三方来源说明

车牌识别使用 [HyperLPR3 0.1.3](https://pypi.org/project/hyperlpr3/0.1.3/)，该软件采用 Apache-2.0 许可，原文见 [上游许可证](licenses/hyperlpr3_license.txt)。

预训练模型为 HyperLPR3 配套的 20230229 版本，来源配置见 [上游配置](https://github.com/szad670401/HyperLPR/blob/9307450f7b7915be18f23a539ec05b41fe6629f4/Prj-Python/hyperlpr3/config/settings.py)，文件位于 [models/20230229/onnx/](src/plate_lpr_server/models/20230229/onnx/)。模型并非本团队自行训练。

其他运行依赖见 [requirements.txt](src/plate_lpr_server/requirements.txt)，遵循各自许可。模型与其他第三方内容不由本项目 GPL 重新授权。
