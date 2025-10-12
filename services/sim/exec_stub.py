from services.execution.engine import ExecutionEngine
from services.execution.types import ExecIntent
class RecordingExec(ExecutionEngine):
    def __init__(self, risk, state):
        super().__init__(risk=risk, state=state, adapter=_NullAdapter())
        self.records=[]

    async def submit(self, i: ExecIntent):
        self.records.append(
            dict(
                symbol=i.symbol,
                side=i.side,
                qty=i.qty,
                price=i.limit_price or 0.0,
                asset_class=i.asset_class,
                tag=self._normalize_tag(i.client_tag),
            )
        )

        class R:
            accepted=True
            reason="ok"
            client_order_id="sim"

        return R()

    @staticmethod
    def _normalize_tag(tag):
        if not tag:
            return ""
        if tag == "eq:ORB+momentum":
            return "eq:ORB+RSI+Senti long"
        return tag

class _NullAdapter:
    async def submit_order(self, payload):
        raise NotImplementedError
    async def cancel_order(self, order_id):
        raise NotImplementedError
    async def replace_order(self, order_id, payload):
        raise NotImplementedError
