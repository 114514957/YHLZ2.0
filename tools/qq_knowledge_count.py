import sqlite3
import sys

con = sqlite3.connect(
    r"C:\Users\ACE_WAN——PROJECT\YHLZ\cache\memstore\memstore.db")
n = con.execute(
    "SELECT COUNT(*) FROM l2_items WHERE type='knowledge' AND status='active'"
).fetchone()[0]
con.close()
print(n)
