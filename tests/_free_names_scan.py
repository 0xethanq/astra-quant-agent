"""未解析自由名检查器（作用域链版）—— 由 tests/audit/test_module_free_names.py 使用。

第一版误报 28 处：没处理①模块级 if/try/for 内的绑定 ②闭包对外层函数参数/局部名的引用。
本版按词法作用域逐层收集绑定名，再做 Load 检查。
"""
import ast, builtins

ALWAYS = {'__file__', '__name__', '__doc__', '__package__', '__spec__', '__loader__',
          '__builtins__', '__debug__', '__class__', 'self', 'cls'}


def _bound_names(node):
    """收集一棵子树里所有**绑定**名（赋值/循环/with/except/import/def/class/global）。"""
    out = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store, ast.Del)):
            out.add(n.id)
        elif isinstance(n, (ast.Import, ast.ImportFrom)):
            out |= {a.asname or a.name.split('.')[0] for a in n.names}
        elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            out.add(n.name)
        elif isinstance(n, ast.ExceptHandler) and n.name:
            out.add(n.name)
        elif isinstance(n, ast.Global):
            out |= set(n.names)
        elif isinstance(n, ast.arg):
            out.add(n.arg)
        elif isinstance(n, ast.comprehension):
            tg = n.target
            for e in (tg.elts if isinstance(tg, (ast.Tuple, ast.List)) else [tg]):
                if isinstance(e, ast.Name):
                    out.add(e.id)
        elif isinstance(n, ast.Lambda):
            out |= {a.arg for a in n.args.args + n.args.kwonlyargs}
    return out


def free_names(path):
    tree = ast.parse(open(path, encoding='utf-8').read())
    module_bound = _bound_names(tree)          # 模块级（含嵌套块）所有绑定
    loads = {}                                  # name -> [func names]

    def visit(node, outer):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            a = node.args
            params = {x.arg for x in list(a.posonlyargs) + list(a.args) + list(a.kwonlyargs)}
            if a.vararg: params.add(a.vararg.arg)
            if a.kwarg: params.add(a.kwarg.arg)
            local = params | _bound_names(node) | set(outer)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for st in node.body:
                    visit(st, local)
            else:
                visit(node.body, local)
            return
        if isinstance(node, (ast.Module, ast.ClassDef)):
            for st in node.body:
                visit(st, outer)
            return
        for child in ast.iter_child_nodes(node):
            visit(child, outer)
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            nm = node.id
            if nm in ALWAYS or hasattr(builtins, nm):
                return
            if nm in module_bound or nm in outer:
                return
            loads.setdefault(nm, 0)
            loads[nm] += 1
    visit(tree, set())
    return loads


if __name__ == '__main__':
    import pathlib, sys
    roots = sys.argv[1:] or ['scripts', 'astra_backend', 'astra_gateway']
    hits, total = [], 0
    for root in roots:
        for p in sorted(pathlib.Path(root).rglob('*.py')):
            if '__pycache__' in str(p):
                continue
            total += 1
            m = free_names(p)
            if m:
                hits.append((str(p), m))
    print(f'扫描 {total} 个模块 → {len(hits)} 个疑似未解析自由名\n')
    for path, m in hits:
        print(f'  ❌ {path}: {", ".join(sorted(m))}')
