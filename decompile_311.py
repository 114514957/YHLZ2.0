"""
Python 3.11 .pyc 反编译器 — 通过 dis 模块提取字节码并重建源码
"""
import dis, marshal, sys, os, struct, types

def decompile_pyc(pyc_path, out_path):
    """从 .pyc 反编译为 .py"""
    with open(pyc_path, 'rb') as f:
        magic = f.read(4)
        flags = struct.unpack('<I', f.read(4))[0]
        # Python 3.11: 16 bytes header
        if (flags & 0x01):  # hash-based
            f.read(8)
        else:
            f.read(4)
        f.read(4)  # timestamp
        f.read(4)  # size
        code = marshal.loads(f.read())
    
    lines = []
    _decompile_code(code, lines, indent=0)
    
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    
    return True

def _decompile_code(code, lines, indent=0):
    """反编译单个 code object"""
    prefix = '    ' * indent
    
    # Module-level: add imports
    if indent == 0:
        lines.append(f'"""Auto-decompiled from {code.co_name}"""')
        lines.append('')
    
    # Extract strings and names used
    names = set()
    for instr in dis.get_instructions(code):
        if instr.opname == 'LOAD_NAME' and instr.argval not in ('__name__', '__doc__'):
            names.add(instr.argval)
        elif instr.opname == 'LOAD_GLOBAL':
            names.add(instr.argval)
        elif instr.opname == 'IMPORT_NAME':
            names.add(instr.argval)
    
    # Extract variable names
    varnames = set(code.co_varnames)
    
    # Try to reconstruct the source from bytecode patterns
    instructions = list(dis.get_instructions(code))
    i = 0
    
    # Track imports
    imports = []
    from_imports = {}
    
    # Simple pattern matching for imports
    while i < len(instructions):
        instr = instructions[i]
        
        if instr.opname == 'LOAD_CONST' and isinstance(instr.argval, int) and instr.argval == 0:
            # LOAD_CONST 0 → IMPORT_NAME → STORE_NAME = import
            if i + 2 < len(instructions) and instructions[i+1].opname == 'IMPORT_NAME' and instructions[i+2].opname == 'STORE_NAME':
                mod = instructions[i+1].argval
                name = instructions[i+2].argval
                if name == mod:
                    imports.append(f"import {mod}")
                else:
                    imports.append(f"import {mod} as {name}")
                i += 3
                continue
        
        if instr.opname == 'LOAD_CONST' and isinstance(instr.argval, int) and instr.argval > 0:
            # from X import Y
            if i + 3 < len(instructions) and instructions[i+1].opname == 'IMPORT_NAME' and instructions[i+2].opname == 'IMPORT_FROM':
                mod = instructions[i+1].argval
                sub = instructions[i+2].argval
                if mod not in from_imports:
                    from_imports[mod] = []
                from_imports[mod].append(sub)
                i += 4
                continue
        
        i += 1
    
    # Output imports
    for imp in sorted(imports):
        lines.append(imp)
    for mod, subs in sorted(from_imports.items()):
        subs_str = ', '.join(sorted(set(subs)))
        lines.append(f"from {mod} import {subs_str}")
    
    if imports or from_imports:
        lines.append('')
    
    # Output constants as strings (docstrings, etc.)
    for const in code.co_consts:
        if isinstance(const, str) and len(const) > 10 and const != code.co_name:
            lines.append(f'# docstring: {const[:80]}...')
    
    # Output variable names
    if varnames:
        lines.append(f'# Variables: {", ".join(sorted(varnames))}')
    
    # Output functions and classes
    for const in code.co_consts:
        if isinstance(const, types.CodeType) and const.co_name != '<lambda>':
            lines.append('')
            if const.co_name[0].isupper():
                lines.append(f'class {const.co_name}:')
                lines.append(f'    """Auto-decompiled class"""')
                lines.append(f'    pass')
            else:
                lines.append(f'def {const.co_name}():')
                lines.append(f'    """Auto-decompiled function"""')
                lines.append(f'    pass')
            lines.append('')
    
    lines.append('')
    lines.append(f'# NOTE: Full decompilation not available for Python 3.11')
    lines.append(f'# This is a skeleton — restore from backup or recreate manually')
    lines.append(f'# Original bytecode instructions: {len(instructions)}')
    
    return lines

if __name__ == '__main__':
    if len(sys.argv) < 3:
        print("Usage: python decompile_311.py <input.pyc> <output.py>")
        sys.exit(1)
    
    decompile_pyc(sys.argv[1], sys.argv[2])
    print(f"Decompiled: {sys.argv[1]} → {sys.argv[2]}")