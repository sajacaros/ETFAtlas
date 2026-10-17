from typing import Dict, Type

from ..base import Node
from .ai_analysis import AIAnalysisNode
from .chart_filter import ChartFilterNode
from .combine import CombineNode
from .result_view import ResultNode
from .source import SourceNode

REGISTRY: Dict[str, Type[Node]] = {
    n.type: n for n in (SourceNode, ChartFilterNode, CombineNode, AIAnalysisNode, ResultNode)
}
