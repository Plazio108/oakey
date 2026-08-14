import ast
import os
import re
from pathlib import Path

puml_output = ["@startuml 'Diagram'"]
puml_output.append("skinparam classAttributeIconSize 0")

classes = {}

def get_visibility(name):
    if name.startswith('__') and name.endswith('__'):
        return '+'
    elif name.startswith('__'):
        return '-'
    elif name.startswith('_'):
        return '#'
    else:
        return '+'

class ClassVisitor(ast.NodeVisitor):
    def __init__(self, module_name):
        self.module_name = module_name
        self.current_class = None

    def visit_ClassDef(self, node):
        class_name = node.name
        is_abstract_class = False
        bases = []
        for base in node.bases:
            base_name = ""
            if isinstance(base, ast.Name):
                base_name = base.id
            elif isinstance(base, ast.Attribute):
                base_name = base.attr
            
            if base_name in ('ABC', 'Protocol'):
                is_abstract_class = True
            elif base_name:
                bases.append(base_name)
        
        methods = []
        fields = {}
        
        for body_node in node.body:
            if isinstance(body_node, ast.FunctionDef):
                is_abstract = False
                for dec in body_node.decorator_list:
                    if isinstance(dec, ast.Name) and dec.id == 'abstractmethod':
                        is_abstract = True
                    elif isinstance(dec, ast.Attribute) and dec.attr == 'abstractmethod':
                        is_abstract = True
                
                if not is_abstract:
                    for stmt in body_node.body:
                        if isinstance(stmt, ast.Raise):
                            if isinstance(stmt.exc, ast.Name) and stmt.exc.id == 'NotImplementedError':
                                is_abstract = True
                                break
                            elif isinstance(stmt.exc, ast.Call) and isinstance(stmt.exc.func, ast.Name) and stmt.exc.func.id == 'NotImplementedError':
                                is_abstract = True
                                break
                
                if is_abstract:
                    is_abstract_class = True
                    
                args = []
                for arg in body_node.args.args:
                    if arg.arg == 'self':
                        continue
                    arg_str = arg.arg
                    if arg.annotation:
                        try:
                            arg_str += f": {ast.unparse(arg.annotation)}"
                        except Exception:
                            pass
                    args.append(arg_str)
                
                MAX_LINE_LEN = 60
                args_lines = []
                current_line = []
                current_len = len(body_node.name) + 1
                
                for arg in args:
                    if current_line and current_len + len(arg) > MAX_LINE_LEN:
                        args_lines.append(", ".join(current_line))
                        current_line = [arg]
                        current_len = 8 + len(arg)
                    else:
                        current_line.append(arg)
                        current_len += len(arg) + 2
                
                if current_line:
                    args_lines.append(", ".join(current_line))
                    
                args_str = ",\\n        ".join(args_lines)
                
                return_type = ""
                if body_node.returns:
                    try:
                        return_type = f": {ast.unparse(body_node.returns)}"
                    except Exception:
                        pass
                
                methods.append({
                    "name": body_node.name,
                    "signature": f"{body_node.name}({args_str}){return_type}",
                    "is_abstract": is_abstract,
                    "is_override": False
                })
                
                for sub_node in ast.walk(body_node):
                    if isinstance(sub_node, ast.Assign):
                        for target in sub_node.targets:
                            if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name) and target.value.id == 'self':
                                type_str = ""
                                if isinstance(sub_node.value, ast.Call) and isinstance(sub_node.value.func, ast.Name):
                                    type_str = sub_node.value.func.id
                                if target.attr not in fields or not fields[target.attr]:
                                    fields[target.attr] = type_str
                    elif isinstance(sub_node, ast.AnnAssign):
                        target = sub_node.target
                        if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name) and target.value.id == 'self':
                            try:
                                fields[target.attr] = ast.unparse(sub_node.annotation)
                            except Exception:
                                pass
            
            elif isinstance(body_node, ast.AnnAssign):
                if isinstance(body_node.target, ast.Name):
                    try:
                        fields[body_node.target.id] = ast.unparse(body_node.annotation)
                    except Exception:
                        pass
            elif isinstance(body_node, ast.Assign):
                for target in body_node.targets:
                    if isinstance(target, ast.Name):
                        if target.id not in fields:
                            fields[target.id] = ""

        classes[class_name] = {
            "module": self.module_name,
            "bases": bases,
            "methods": methods,
            "fields": fields,
            "is_abstract": is_abstract_class
        }
        self.generic_visit(node)

src_path = Path("src")
for py_file in src_path.rglob("*.py"):
    module_name = py_file.relative_to(src_path).with_suffix('').parts
    module_name = ".".join(module_name)
    try:
        with open(py_file, 'r', encoding='utf-8') as f:
            content = f.read()
        tree = ast.parse(content)
        visitor = ClassVisitor(module_name)
        visitor.visit(tree)
    except Exception as e:
        print(f"Error parsing {py_file}: {e}")

def get_ancestor_methods(class_name, classes_dict, visited=None):
    if visited is None:
        visited = set()
    if class_name in visited:
        return set()
    visited.add(class_name)
    
    ancestor_methods = set()
    if class_name in classes_dict:
        bases = classes_dict[class_name]["bases"]
        for base in bases:
            if base in classes_dict:
                for m in classes_dict[base]["methods"]:
                    ancestor_methods.add(m["name"])
                ancestor_methods.update(get_ancestor_methods(base, classes_dict, visited))
    return ancestor_methods

for class_name, info in classes.items():
    ancestors_meths = get_ancestor_methods(class_name, classes)
    for method in info["methods"]:
        if method["name"] in ancestors_meths and method["name"] != "__init__":
            method["is_override"] = True

modules = {}
for class_name, info in classes.items():
    mod = info["module"]
    if mod not in modules:
        modules[mod] = []
    modules[mod].append((class_name, info))

for mod, mod_classes in modules.items():
    puml_output.append(f'package "{mod}" {{')
    for class_name, info in mod_classes:
        class_type = "abstract class" if info["is_abstract"] else "class"
        puml_output.append(f'  {class_type} {class_name} {{')
        for field_name in sorted(info["fields"].keys()):
            field_type = info["fields"][field_name]
            vis = get_visibility(field_name)
            if field_type:
                puml_output.append(f'    {vis}{field_name}: {field_type}')
            else:
                puml_output.append(f'    {vis}{field_name}')
        for method in info["methods"]:
            vis = get_visibility(method["name"])
            abs_modifier = "{abstract} " if method["is_abstract"] else ""
            override_modifier = " <<override>>" if method["is_override"] else ""
            puml_output.append(f'    {abs_modifier}{vis}{method["signature"]}{override_modifier}')
        puml_output.append('  }')
    puml_output.append('}')

known_classes = set(classes.keys())

for class_name, info in classes.items():
    for base in info["bases"]:
        puml_output.append(f'{base} <|-- {class_name}')
    
    for field_name, field_type in info["fields"].items():
        if field_type:
            for known in known_classes:
                if known == class_name:
                    continue
                if re.search(r'\b' + re.escape(known) + r'\b', field_type):
                    puml_output.append(f'{class_name} o-- {known} : {field_name}')

puml_output.append("@enduml")

with open("diagram.puml", "w", encoding='utf-8') as f:
    f.write("\n".join(puml_output))
print("Diagram written to diagram.puml")
