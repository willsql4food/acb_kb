from pyspark.sql.types import StructType
import os

def schema_difference(
    schema_a: StructType, 
    schema_b: StructType, 
    show_type_diffs: bool = True,
    alias_a: str = "A", 
    alias_b: str = "B"
    ):
    
    """
    Compare two schemas and return a list of the fields in one or the other but not both

    Parameters
    --------------------
    schema_a: StructType
        First or 'left' schema to compare 
    
    schema_b: StructType
        Second or 'right' schema to compare

    show_type_diffs: bool = True
        True = show fields with the same name but different types
        False = show only field name differences

    alias_a: str
        Optional - Alias for left schema name in results

    alias_b: str
        Optional - Alias for right schema name in results

    Returns
    --------------------
    list
        The elements of either schema which are not in the other
    """ 
    ret = []

    if not show_type_diffs:
        a = schema_a.fieldNames()
        b = schema_b.fieldNames()
    else:
        a = schema_a
        b = schema_b

    for f in a:
        if f not in b:
            ret.append((alias_a, f)) 

    for f in b:
        if f not in a:
            ret.append((alias_b, f)) 
    return ret

def directory_tree(
     path: str,
    level: int = 0
):
    """
    Returns a full directory listing of all folders and sub-folders
    
    Parameters
    --------------------
    path
        The directory path to interrogate

    level
        The depth of the child in its heirarchy

    Returns
    --------------------
    list
        Given directory and all its descendents
    """
    _dirs = []
    _df = os.scandir(path)

    if level < 20:
        for d in _df:
            if d.is_dir():
                _dirs.append(d.path)
                _dirs += directory_tree(d.path, level + 1)

    return _dirs