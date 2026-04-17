from lkr.codemode.main import run_python_code

code = """
me_obj = me()
print("Name:", me_obj["first_name"], me_obj["last_name"])
personal_folder = folder(me_obj["personal_folder_id"])
print("Folders:")
for f in folder_children(personal_folder["id"]):
    print(" - " + f["name"])
print("Dashboards:")
for d in personal_folder["dashboards"]:
    print(" - " + d["title"])
print("Looks:")
for l in personal_folder["looks"]:
    print(" - " + l["title"])
"""

print(run_python_code(code))
