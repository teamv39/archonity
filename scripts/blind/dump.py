"""dump.py <dump.sql> <db.table> [фильтр-подстрока] -- строки таблицы с именами колонок."""
import re, sys

src, want = sys.argv[1], sys.argv[2]
flt = sys.argv[3] if len(sys.argv) > 3 else None
db = None
cols = {}
cur = None
rows = []
text = open(src, encoding="latin-1").read().splitlines()
for line in text:
    m = re.match(r"USE `(\w+)`", line)
    if m:
        db = m.group(1)
    m = re.match(r"CREATE TABLE `(\w+)`", line)
    if m:
        cur = f"{db}.{m.group(1)}"
        cols[cur] = []
        continue
    if cur and re.match(r"\s+`(\w+)`", line):
        cols[cur].append(re.match(r"\s+`(\w+)`", line).group(1))
    if line.startswith(")"):
        cur = None
    m = re.match(r"INSERT INTO `(\w+)` VALUES (.*);$", line)
    if m and f"{db}.{m.group(1)}" == want:
        body = m.group(2)
        # разбор кортежей с учётом строк в кавычках
        i, n = 0, len(body)
        while i < n:
            if body[i] == "(":
                vals, buf, q = [], "", False
                i += 1
                while i < n:
                    c = body[i]
                    if q:
                        if c == "\\":
                            buf += body[i + 1]; i += 2; continue
                        if c == "'":
                            q = False
                        else:
                            buf += c
                    else:
                        if c == "'":
                            q = True
                        elif c == ",":
                            vals.append(buf); buf = ""
                        elif c == ")":
                            vals.append(buf); break
                        else:
                            buf += c
                    i += 1
                rows.append(vals)
            i += 1
if want not in cols:
    print("таблицы:", sorted(cols))
    sys.exit(1)
print(want, cols[want], len(rows), "строк")
for r in rows:
    s = " | ".join(f"{c}={v}" for c, v in zip(cols[want], r))
    if not flt or flt in s:
        print(" ", s)
