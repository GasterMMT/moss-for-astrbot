"""MOSS 语音 Provider 包（MOSI 官方 MossAPI，https://api.mosi.cn）。

导入本包下的模块即会向 AstrBot 注册对应的 Provider 适配器：

- moss_tts_cloud: MOSS 官方单人语音生成（POST /v1/audio/speech）
- moss_stt_cloud:  MOSS 官方音频转写（POST /v1/audio/transcriptions）
"""

from .moss_stt_cloud import MossSTTCloudProvider
from .moss_tts_cloud import MossTTSCloudProvider

__all__ = ["MossSTTCloudProvider", "MossTTSCloudProvider"]
