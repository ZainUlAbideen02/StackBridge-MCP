"""Parser for extracting SQLAlchemy models, fields, and relationships."""

import re
from typing import List, Optional, Tuple
from tree_sitter import Parser, Language, Node
from tree_sitter_python import language as python_language

from stackbridge.core.models import SQLAlchemyModelInfo, FieldInfo


def extract_sqlalchemy_models(code: str, file_path: str) -> List[SQLAlchemyModelInfo]:
    """
    Extract SQLAlchemy 2.0 Declarative Models and Pydantic v2 schemas from Python code.
    
    Args:
        code: The source code as a string
        file_path: Path to the file being parsed
        
    Returns:
        List of SQLAlchemyModelInfo objects representing detected models/schemas
    """
    lang = Language(python_language())
    parser = Parser(lang)
    tree = parser.parse(code.encode('utf-8'))
    root_node = tree.root_node
    
    models: List[SQLAlchemyModelInfo] = []
    
    # Query for class definitions
    query_string = """
        (class_definition
            name: (identifier) @class_name
            body: (block) @class_body
        ) @class_def
    """
    
    query = lang.query(query_string)
    captures_dict = query.captures(root_node)
    
    class_def_nodes = captures_dict.get('class_def', [])
    
    for class_node in class_def_nodes:
        model_info = _extract_model_from_class(class_node, code, file_path)
        if model_info:
            models.append(model_info)
    
    return models


def _extract_model_from_class(class_node: Node, code: str, file_path: str) -> Optional[SQLAlchemyModelInfo]:
    """
    Extract model information from a class definition node.
    
    Checks if the class is a SQLAlchemy model or Pydantic schema by examining:
    - Base class names (e.g., inherits from Base, BaseModel)
    - Presence of __tablename__ attribute
    - Presence of Mapped types or Column definitions
    """
    # Get class name
    class_name_node = class_node.child_by_field_name('name')
    if not class_name_node:
        return None
    
    class_name = class_name_node.text.decode('utf-8')
    
    # Get line number (tree-sitter uses 0-indexed rows)
    line_number = class_node.start_point[0] + 1
    
    # Check base classes to determine if it's a SQLAlchemy model or Pydantic schema
    bases = _get_base_classes(class_node)
    is_sqlalchemy = any(base in ['Base', 'DeclarativeBase', 'orm.DeclarativeBase'] for base in bases)
    is_pydantic = any(base in ['BaseModel', 'pydantic.BaseModel'] for base in bases)
    
    if not is_sqlalchemy and not is_pydantic:
        # Also check for __tablename__ to catch SQLAlchemy models without explicit Base
        class_body = class_node.child_by_field_name('body')
        if class_body:
            tablename = _extract_tablename(class_body, code)
            if tablename:
                is_sqlalchemy = True
    
    if not is_sqlalchemy and not is_pydantic:
        return None
    
    # Get class body
    class_body = class_node.child_by_field_name('body')
    if not class_body:
        return SQLAlchemyModelInfo(
            file_path=file_path,
            line=line_number,
            class_name=class_name,
            table_name=None,
            fields=[],
            relationships=[]
        )
    
    # Extract table name for SQLAlchemy models
    table_name = _extract_tablename(class_body, code) if is_sqlalchemy else None
    
    # Extract fields
    fields = _extract_fields(class_body, code)
    
    # Extract relationships
    relationships = _extract_relationships(class_body, code)
    
    return SQLAlchemyModelInfo(
        file_path=file_path,
        line=line_number,
        class_name=class_name,
        table_name=table_name,
        fields=fields,
        relationships=relationships
    )


def _get_base_classes(class_node: Node) -> List[str]:
    """Extract base class names from a class definition."""
    bases = []
    superclass_node = class_node.child_by_field_name('superclasses')
    if superclass_node:
        # The superclasses field is an argument_list containing the base classes
        for child in superclass_node.children:
            if child.type == 'identifier':
                bases.append(child.text.decode('utf-8'))
            elif child.type == 'attribute':
                # Handle cases like 'sqlalchemy.orm.DeclarativeBase'
                bases.append(child.text.decode('utf-8'))
    return bases


def _extract_tablename(class_body: Node, code: str) -> Optional[str]:
    """Extract __tablename__ value from class body."""
    for child in class_body.children:
        # Handle expression_statement wrapping assignment
        if child.type == 'expression_statement':
            for stmt_child in child.children:
                if stmt_child.type == 'assignment':
                    left_node = stmt_child.child_by_field_name('left')
                    right_node = stmt_child.child_by_field_name('right')
                    
                    if left_node and left_node.text.decode('utf-8') == '__tablename__':
                        if right_node and right_node.type == 'string':
                            content = right_node.text.decode('utf-8')
                            # Remove quotes
                            if (content.startswith('"') and content.endswith('"')) or \
                               (content.startswith("'") and content.endswith("'")):
                                return content[1:-1]
        # Also handle direct assignment nodes
        elif child.type == 'assignment':
            left_node = child.child_by_field_name('left')
            right_node = child.child_by_field_name('right')
            
            if left_node and left_node.text.decode('utf-8') == '__tablename__':
                if right_node and right_node.type == 'string':
                    content = right_node.text.decode('utf-8')
                    # Remove quotes
                    if (content.startswith('"') and content.endswith('"')) or \
                       (content.startswith("'") and content.endswith("'")):
                        return content[1:-1]
    return None


def _extract_fields(class_body: Node, code: str) -> List[FieldInfo]:
    """Extract field/column definitions from class body."""
    fields: List[FieldInfo] = []
    
    for child in class_body.children:
        field_info = None
        
        # Handle expression_statement wrapping assignment (common in class bodies)
        if child.type == 'expression_statement':
            for stmt_child in child.children:
                if stmt_child.type == 'assignment':
                    field_info = _parse_assignment(stmt_child, code)
                    break
        
        # Handle direct annotated_assignment nodes
        elif child.type == 'annotated_assignment':
            field_info = _parse_annotated_assignment(child, code)
        
        # Handle direct assignment nodes
        elif child.type == 'assignment':
            field_info = _parse_assignment(child, code)
        
        if field_info:
            fields.append(field_info)
    
    return fields


def _parse_annotated_assignment(node: Node, code: str) -> Optional[FieldInfo]:
    """Parse an annotated assignment like 'email: str' or 'id: int'."""
    left_node = node.child_by_field_name('left')
    type_node = node.child_by_field_name('type')
    right_node = node.child_by_field_name('right')
    
    if not left_node or not type_node:
        return None
    
    name = left_node.text.decode('utf-8')
    type_annotation = type_node.text.decode('utf-8')
    
    # Skip private attributes
    if name.startswith('_'):
        return None
    
    # Check if nullable (Optional[...] or [...] | None)
    is_nullable = _is_type_nullable(type_annotation)
    
    # Check if primary key
    is_primary_key = _check_primary_key(right_node, code) if right_node else False
    
    return FieldInfo(
        name=name,
        type_annotation=type_annotation,
        is_nullable=is_nullable,
        is_primary_key=is_primary_key
    )


def _parse_assignment(node: Node, code: str) -> Optional[FieldInfo]:
    """Parse an assignment like 'id = Column(Integer)' or 'name: Mapped[str] = mapped_column(...)'."""
    left_node = node.child_by_field_name('left')
    right_node = node.child_by_field_name('right')
    
    if not left_node:
        return None
    
    name = left_node.text.decode('utf-8')
    
    # Skip private attributes and special methods
    if name.startswith('_'):
        return None
    
    type_annotation = ""
    is_nullable = False
    is_primary_key = False
    
    # Check for type annotation in the left side (e.g., name: Mapped[str])
    if node.child_by_field_name('type'):
        type_annotation = node.child_by_field_name('type').text.decode('utf-8')
        is_nullable = _is_type_nullable(type_annotation)
    
    # Analyze the right side for Column/relationship info
    if right_node:
        right_text = right_node.text.decode('utf-8')
        
        # Detect Column types
        column_match = re.search(r'Column\(([^)]+)\)', right_text)
        if column_match:
            col_args = column_match.group(1)
            # Extract type from Column(Integer), Column(String(50)), etc.
            type_match = re.search(r'^(\w+)', col_args)
            if type_match and not type_annotation:
                type_annotation = type_match.group(1)
            
            # Check for nullable
            if 'nullable=True' in col_args:
                is_nullable = True
            elif 'nullable=False' in col_args:
                is_nullable = False
            
            # Check for primary_key
            if 'primary_key=True' in col_args:
                is_primary_key = True
        
        # Detect mapped_column for SQLAlchemy 2.0
        mapped_match = re.search(r'mapped_column\(([^)]+)\)', right_text)
        if mapped_match:
            mc_args = mapped_match.group(1)
            if 'primary_key=True' in mc_args:
                is_primary_key = True
            if 'nullable=True' in mc_args:
                is_nullable = True
        
        # If no type found yet, try to infer from Mapped[...]
        if not type_annotation:
            mapped_type_match = re.search(r'Mapped\[([^\]]+)\]', right_text)
            if mapped_type_match:
                type_annotation = f"Mapped[{mapped_type_match.group(1)}]"
    
    if not type_annotation:
        type_annotation = "Any"
    
    return FieldInfo(
        name=name,
        type_annotation=type_annotation,
        is_nullable=is_nullable,
        is_primary_key=is_primary_key
    )


def _is_type_nullable(type_annotation: str) -> bool:
    """Check if a type annotation indicates nullability."""
    # Optional[X] or Union[X, None] or X | None
    if type_annotation.startswith('Optional['):
        return True
    if 'None' in type_annotation and ('Union' in type_annotation or '|' in type_annotation):
        return True
    if ' | None' in type_annotation or '| None' in type_annotation:
        return True
    return False


def _check_primary_key(right_node: Node, code: str) -> bool:
    """Check if a field is marked as primary key."""
    right_text = right_node.text.decode('utf-8')
    return 'primary_key=True' in right_text


def _extract_relationships(class_body: Node, code: str) -> List[str]:
    """Extract relationship definitions from class body."""
    relationships: List[str] = []
    
    for child in class_body.children:
        right_node = None
        
        # Handle expression_statement wrapping assignment
        if child.type == 'expression_statement':
            for stmt_child in child.children:
                if stmt_child.type == 'assignment':
                    right_node = stmt_child.child_by_field_name('right')
                    break
        # Handle direct assignment nodes
        elif child.type == 'assignment':
            right_node = child.child_by_field_name('right')
        
        if right_node:
            right_text = right_node.text.decode('utf-8')
            
            # Match relationship("ModelName", ...) or relationship(ModelName, ...)
            rel_match = re.search(r'relationship\s*\(\s*["\']?(\w+)["\']?', right_text)
            if rel_match:
                related_model = rel_match.group(1)
                relationships.append(related_model)
    
    return relationships
