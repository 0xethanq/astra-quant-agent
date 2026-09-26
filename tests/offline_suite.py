"""Run discovery with fail-closed network and real-resource tripwires.

Usage: python3 -m tests.offline_suite
The same guard can be installed by a sitecustomize harness before standard
``python3 -m unittest discover -s tests -t .``. This does not alter tests/__init__.
This is a Python audit guard, not an OS sandbox for arbitrary native children.
"""
import hashlib
import os
from pathlib import Path
import socket
import sys
import unittest


class OfflineGuard:
    def __init__(self, root=None):
        self.root = Path(root or Path(__file__).resolve().parents[1]).resolve()
        self.roots = {self.root}
        # A linked worktree must also protect the original workspace resources.
        git_file = self.root / '.git'
        if git_file.is_file():
            git_dir = Path(git_file.read_text().strip().removeprefix('gitdir: '))
            self.roots.add(git_dir.resolve().parents[2])
        self.attempts = []
        self.writes = []
        self.children = []
        self.before = self.fingerprint()

    def fingerprint(self):
        """Metadata fingerprint: never read .env, key, ciphertext or config bytes.

        Nanosecond ctime catches write-and-restore; ignore atime (read-only access
        is allowed). The write audit additionally detects attempted mutations.
        """
        result = {}
        for root in self.roots:
            paths = {root / '.env', root / 'data/.astra_secret_key',
                     root / 'data/astra_secrets.enc'}
            # Active services in the original workspace may update their caches
            # concurrently. Monitor all JSON configuration in THIS worktree;
            # original-workspace credentials are monitored without reading them.
            if root == self.root:
                paths.update((root / 'data').rglob('*.json'))
            for path in paths:
                if path.name.endswith('.lock') or path.is_dir():
                    continue
                stat = path.stat() if path.exists() else None
                result[str(path)] = ((stat.st_dev, stat.st_ino, stat.st_size,
                                      stat.st_mtime_ns, stat.st_ctime_ns, stat.st_mode)
                                     if stat else None)
        return result

    def protected(self, value, dir_fd=None):
        if not isinstance(value, (str, bytes, os.PathLike)):
            return False
        path = Path(os.fsdecode(value))
        if not path.is_absolute() and dir_fd is not None and dir_fd != -1:
            path = Path(os.readlink(f'/proc/self/fd/{dir_fd}')) / path
        path = path.resolve()
        return not path.name.endswith('.lock') and any(
            path == root / '.env' or path.is_relative_to(root / 'data')
            for root in self.roots)

    @staticmethod
    def _is_loopback_addr(address) -> bool:
        """audit `socket.connect` / `socket.sendto` 的 args[1]（address tuple）。
        只认 **字面回环**：127.0.0.0/8、::1、以及主机名 'localhost'
        （它经 getaddrinfo 的放行判断同规则）。AF_UNIX 等一律不放行（保守）。
        """
        if not (isinstance(address, tuple) and address):
            return False
        return OfflineGuard._is_loopback_host(address[0])

    @staticmethod
    def _is_loopback_host(host) -> bool:
        if not isinstance(host, str) or not host:
            return False
        if host == 'localhost':
            return True
        try:
            import ipaddress
            return ipaddress.ip_address(host).is_loopback
        except ValueError:
            return False

    def audit(self, event, args):
        if event in ('socket.connect', 'socket.sendto'):
            # ⚠️ 第七十八刀：loopback 放行。护栏的目标是"不外泄"，
            # `127.0.0.1`/`::1` 的连接**永不离开本机**（本机回环由内核直达）。
            # 一刀切拦掉会误伤"起本地 HTTP server 验 HTTP 语义"的用例
            # （safe_urlopen 的 302 拒绝、telegram 的业务码）—— 它们的出站
            # 测试目标本来就是 localhost，被拦反而**测不到真行为**。
            # ⚠️ 实测 audit 形状：connect/sendto 都是 (sock, address) ——
            # buffer **不在** audit args 里，两类事件统一取 args[1]。
            if not self._is_loopback_addr(args[1]):
                self.attempts.append(event)
                self._log_diagnostics(event, args)
                raise RuntimeError('Offline suite blocked network: ' + event)
            return
        if event == 'socket.getaddrinfo':
            # 主机名解析只有"解析回环字面量"是本地行为；真实主机名要发 DNS
            # 查询（外部） ⇒ 仍全拦。
            if not self._is_loopback_host(args[0]):
                self.attempts.append(event)
                self._log_diagnostics(event, args)
                raise RuntimeError('Offline suite blocked network: ' + event)
            return
        if event == 'subprocess.Popen':
            command = args[1]
            tokens = list(command) if isinstance(command, (list, tuple)) else [str(command)]
            executable = Path(str(tokens[0])).name
            # Record executable/subcommand only: never log command bodies or env.
            label = executable + (' ' + str(tokens[1]) if len(tokens) > 1 else '')
            self.children.append(label)
            # Only reviewed local tools and the pure risk-constant import probe.
            # An arbitrary Python/shell child must not bypass the socket guard.
            allowed = (executable == 'uname' and tokens[1:] == ['-p']) or (
                executable == 'grep' and tokens[1:] == [
                    '-rn', 'gemini-3.8-flash-high', '--include=*.py',
                    '--include=*.ts', '--include=*.vue', 'astra_backend',
                    'scripts', 'frontend/src']) or (
                executable in ('python3', 'python', Path(sys.executable).name)
                and len(tokens) == 3 and tokens[1] == '-c'
                and hashlib.sha256(tokens[2].encode()).hexdigest() ==
                'ae478ea673237b4bb4e386e0df78313d11ee02594816f1d3d2bf1e2213789b37') or (
                # ⚠️ 第七十八刀：git **只读**子命令白名单。verbatim 对拍门全靠
                # `git show <rev>:<path>` 取"抽取前原文"当基准 —— 拦掉它们
                # 不是"更安全"，而是**把最值钱的回归覆盖在离线环境里弄瞎**。
                # 论证无外泄/无副作用：show/rev-parse 只读本地 object DB、
                # 输出到 stdout，不发网络（fetch/push/clone 等一律不在列）。
                # 参数形状收紧：`show` 恰好一个 `<rev>:<path>`；`rev-parse --short <ref>`。
                (executable == 'git' and (
                    (tokens[1:2] == ['show'] and len(tokens) == 3
                     and ':' in str(tokens[2])
                     and not str(tokens[2]).startswith('-'))
                    or (tokens[1:3] == ['rev-parse', '--short'] and len(tokens) == 4
                        and not str(tokens[3]).startswith('-'))
                )))
            if not allowed:
                self.attempts.append('external child process: ' + executable)
                raise RuntimeError('Offline suite blocked external child process')
        if event == 'os.system':
            self.attempts.append('shell command')
            raise RuntimeError('Offline suite blocked shell command')
        targets = []
        if event == 'open' and isinstance(args[2], int) and args[2] & (
                os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC):
            targets = [(args[0], None)]
        elif event in ('os.remove', 'os.rmdir'):
            targets = [(args[0], args[1])]
        elif event == 'os.rename':
            targets = [(args[0], args[2]), (args[1], args[3])]
        for target, dir_fd in targets:
            if self.protected(target, dir_fd):
                self.writes.append(str(target))
                # ⚠️ 第七十七刀：写拦截原先是**归因盲区** —— 网络/spawn 拦截都
                # 过 `_log_diagnostics` 记栈，唯独这里直接 raise。实测 17 个
                # `.llm_models.json-*` 尝试被 raise 后又被调用方 try/except
                # 吞掉 ⇒ 套件零报错、只在汇总里露一次，永远查不到"是谁写的"。
                self._log_diagnostics('protected-write', args[:2])
                raise RuntimeError('Offline suite blocked real resource mutation')

    DIAG_LOG = '/tmp/offline_guard_diagnostics.log'

    def _log_diagnostics(self, event, args):
        """Append-only attribution: record the blocking call stack. Never
        suppresses or alters the fail-closed raise above; writes outside the
        protected roots and never reads config bytes."""
        try:
            import pathlib
            import traceback
            stack = traceback.extract_stack()[:-3]
            test_frames = [f for f in stack
                           # 支持 tests/ 下的子目录（第 138 刀按域分子目录）
                           if ('/tests/' in f.filename and pathlib.Path(f.filename).name.startswith('test_'))
                           or '/unittest/case.py' in f.filename]
            origin = (f'{test_frames[-1].filename.rsplit("/", 1)[-1]}:{test_frames[-1].lineno}'
                      f' in {test_frames[-1].name}' if test_frames else 'no-test-frame')
            with open(self.DIAG_LOG, 'a', encoding='utf-8') as handle:
                handle.write(f'--- [{len(self.attempts)}] {event} origin={origin}\n')
                for frame in stack[-14:]:
                    handle.write(f'    {frame.filename}:{frame.lineno} in {frame.name}\n')
        except Exception:
            pass  # diagnostics must never mask the guard

    def install(self):
        sys.addaudithook(self.audit)
        return self

    def prove_connection_guard(self):
        # Numeric address bypasses DNS: demonstrate TCP egress denial on BOTH
        # HTTP and HTTPS ports, before an OS connect can happen (TEST-NET-1).
        start = len(self.attempts)
        for port in (80, 443):
            with socket.socket() as sock:
                try:
                    sock.connect(('192.0.2.1', port))
                except RuntimeError as exc:
                    if 'Offline suite blocked network' not in str(exc):
                        raise
                else:
                    raise AssertionError('Connection guard did not fire')
        assert self.attempts[start:] == ['socket.connect', 'socket.connect']
        del self.attempts[start:]
        # ⚠️ 第七十八刀对称探针：回环**必须放行** —— 没有这条，"回环判据"
        # 哪天被改坏会静默退回"拦一切"，把误伤重新藏回噪声里。
        with socket.socket() as sock:
            n0 = len(self.attempts)
            try:
                sock.connect(('127.0.0.1', 1))     # 大概率 refused（OS 错误）
            except RuntimeError as exc:
                if 'Offline suite blocked network' in str(exc):
                    raise AssertionError('Loopback connect must NOT be blocked')
            except OSError:
                pass                                # ECONNREFUSED 等 = 穿过了护栏 ✓
            assert len(self.attempts) == n0, "回环连接被记成了网络尝试"
        print('EGRESS_GUARD_SELF_TEST: HTTP/80 + HTTPS/443 blocked; loopback allowed')

    def report(self):
        after = self.fingerprint()
        changed = sorted(k for k in self.before.keys() | after.keys()
                         if self.before.get(k) != after.get(k))
        print('NETWORK_ATTEMPTS:', self.attempts)
        print('CONFIG_FINGERPRINT_CHANGES:', changed)
        print('CONFIG_WRITE_ATTEMPTS:', sorted(set(self.writes)))
        print('LOCAL_SUBPROCESSES:', sorted(set(self.children)))
        return not (self.attempts or changed or self.writes)


def main():
    # 显式标记：让"会 spawn 子进程的测试"能在**spawn 之前**自行跳过。
    # 否则它们会被 audit hook 拦下抛 RuntimeError（套件变脏 + 报 ERROR），
    # 而它们本意只是"本环境无法验证"。判据必须**先于**子进程存在。
    os.environ['OFFLINE_SUITE_RUNNING'] = '1'
    guard = OfflineGuard().install()
    os.chdir(guard.root)
    guard.prove_connection_guard()
    suite = unittest.defaultTestLoader.discover('tests', top_level_dir='.')
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    clean = guard.report()
    return 0 if result.wasSuccessful() and clean else 1


if __name__ == '__main__':
    raise SystemExit(main())
