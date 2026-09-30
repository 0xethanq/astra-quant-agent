"""Deterministic V5 wire fixture; never replaces protection/trading algorithms."""
import copy
import io
import json
from urllib.parse import urlsplit
from unittest.mock import patch


class AlgoHTTP:
    def __init__(self):
        self.requests = []
        self.rows = [self.row(side=side) for side in ('long', 'short')]
        self.pending = []
        self.failures = {}

    @staticmethod
    def row(side='long', size='100', inst='ETH-USDT-SWAP', sl='2400'):
        return dict(algoId='algo_' + side, instId=inst, state='live',
                    posSide=side, side='sell' if side == 'long' else 'buy',
                    reduceOnly='true', sz=size, tpTriggerPx='2600', slTriggerPx=sl)

    def calls(self, path):
        return [(method, body) for method, route, body in self.requests if route == path]

    def __call__(self, req, timeout=None):
        path = urlsplit(req.full_url).path
        body = json.loads(req.data) if req.data else None
        self.requests.append((req.get_method(), path, body))
        headers = dict((k.lower(), v) for k, v in req.header_items())
        assert headers['ok-access-key'] == 'fixture-key'
        assert headers['x-simulated-trading'] == '1'
        assert headers['ok-access-sign']
        if path in self.failures:
            payload = self.failures[path]
        else:
            if path.endswith('/orders-algo-pending'):
                rows = self.pending.pop(0) if self.pending else self.rows
            elif path.endswith('/order-algo'):
                # 每次下单给**唯一** algoId（双腿场景下两条腿若共用一个 id，
                # "认腿"就无从验证 —— 2026-09-29 持仓中调整止盈正是按 id 认腿的）。
                self._created = getattr(self, '_created', 0) + 1
                algo_id = 'created-%d' % self._created
                row = dict(body, algoId=algo_id, state='live')
                self.rows.append(row)
                rows = [{'algoId': algo_id, 'sCode': '0'}]
            elif path.endswith('/amend-algos'):
                # V5 amend-algos：**一个对象**，可同时带新止损与新止盈。
                # 2026-09-29：fixture 需如实建模 `newTpTriggerPx`（持仓中调整止盈
                # 的生产路径就是靠它），否则"改了止盈"在夹具里看不出效果。
                assert isinstance(body, dict) and body['instId']
                for row in self.rows:
                    if row['algoId'] == body['algoId'] and row['instId'] == body['instId']:
                        row['slTriggerPx'] = body['newSlTriggerPx']
                        if body.get('newTpTriggerPx') is not None:
                            row['tpTriggerPx'] = body['newTpTriggerPx']
                rows = [{'algoId': body['algoId'], 'sCode': '0'}]
            elif path.endswith('/cancel-algos'):
                # V5 cancel-algos：**一个数组** [{instId, algoId}]。双腿编排是
                # "先挂后撤"（新腿确认后才撤旧腿），所以这条路径必须可被夹具承接。
                assert isinstance(body, list) and body, 'cancel-algos 必须是数组'
                for item in body:
                    self.rows = [r for r in self.rows if r['algoId'] != item['algoId']]
                rows = [{'algoId': item['algoId'], 'sCode': '0'} for item in body]
            elif path.endswith(('/orders-pending', '/positions')):
                rows = []
            elif path.endswith('/close-position'):
                rows = [{'instId': body['instId'], 'sCode': '0'}]
            else:
                raise AssertionError('Unexpected HTTP request: ' + req.full_url)
            payload = {'code': '0', 'data': copy.deepcopy(rows)}
        return io.BytesIO(json.dumps(payload).encode())


def install_http(test, trader):
    from scripts import okx_runtime
    # Restore even an earlier caller's frozen context; do not consult .env/secrets.
    frozen = patch.object(okx_runtime, '_FROZEN_ENVIRONMENT', None)
    frozen.start()
    test.addCleanup(frozen.stop)
    okx_runtime.freeze_environment(dict(ASTRA_OKX_ENV='demo', OKX_DEMO_API_KEY='fixture-key',
                                      OKX_DEMO_SECRET_KEY='fixture-secret', OKX_DEMO_PASSPHRASE='fixture-pass'))
    wire = AlgoHTTP()
    p = patch.object(trader.okx_rest, 'urlopen', side_effect=wire)
    p.start()
    test.addCleanup(p.stop)
    for name in ('record_trade', 'record_signal_snapshot', 'add_stop_cooldown', 'notify_trade_close'):
        p = patch.object(trader, name)
        p.start()
        test.addCleanup(p.stop)
    p = patch.object(trader.time, 'sleep')
    p.start()
    test.addCleanup(p.stop)
    return wire
