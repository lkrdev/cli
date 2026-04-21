from lkr.codemode.main import run_python_code

# Find me all my dashboards and looks within all my personal folder and nested folders

code = """
me_obj = me()
personal_folder_id = me_obj["personal_folder_id"]

def print_folder(folder_id, indent):
    f = folder(folder_id)
    print(indent + "+ Folder: " + f["name"])
    
    if "dashboards" in f and f["dashboards"]:
        for d in f["dashboards"]:
            print(indent + "  - Dashboard: " + d["title"])
            
    if "looks" in f and f["looks"]:
        for l in f["looks"]:
            print(indent + "  - Look: " + l["title"])
            
    children = folder_children(folder_id)
    for child in children:
        print_folder(child["id"], indent + "  ")

print_folder(personal_folder_id, "")
"""

print(run_python_code(code))
