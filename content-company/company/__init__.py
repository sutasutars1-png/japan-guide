"""AI コンテンツ販売会社 OS (Company OS).

ロードマップ (AI自律型note運営会社) の §41 Step 1 に相当する「AI会社の
OS部分」を、標準ライブラリのみで実装したパッケージ。

外部 AI API を必須にしない (§36「Proサブスク範囲内のみ」)。データはすべて
ローカル JSON / JSONL ファイル (§26) に保存する。実際の LLM 生成は
``AgentRunner`` 差し込みで後から Claude Code / ai-os に接続できる構造にして
あり、既定では決定論的なテンプレート生成 (``TemplateRunner``) で動く。
"""

from .config import Config, load_config
from .storage import Storage

__all__ = ["Config", "load_config", "Storage", "__version__"]

__version__ = "0.1.0"
