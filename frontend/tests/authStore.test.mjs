import { test } from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'

test('auth.ts 具备升级韧性与无感兼容契约', () => {
  const authSource = fs.readFileSync(path.resolve('src/stores/auth.ts'), 'utf-8')

  // 1. 验证历史 key 兼容逻辑存在
  assert.match(
    authSource,
    /r20\.admin\.session\.id/,
    '必须包含旧代号 r20.admin.session.id 的平滑迁移逻辑'
  )
  assert.match(
    authSource,
    /r20\.admin\.session\.user/,
    '必须包含旧代号 r20.admin.session.user 的平滑迁移逻辑'
  )

  // 2. 验证 validateSession 严禁在 !resp.ok 时一刀切登出（防网关 502/503 误踢）
  assert.match(
    authSource,
    /resp\.status === 401/,
    '必须且仅在明确收到 401 Unauthorized 时才执行 logout()'
  )

  // 3. 验证网络异常或服务器重启不清空本地会话
  assert.doesNotMatch(
    authSource,
    /if\s*\(!resp\.ok\)\s*\{\s*logout\(\)/,
    '严禁在 !resp.ok 时无脑调用 logout()，否则服务升级或网关 502 会立刻摧毁用户登录态'
  )

  // 4. 验证 restoreSession 在只有 savedToken 没有 savedUser 时也允许恢复
  assert.match(
    authSource,
    /if\s*\(savedToken\)\s*\{/,
    '只要 savedToken 存在即应允许恢复 token 并异步校验，不能因为 user 缺失而直接拒登'
  )
})
