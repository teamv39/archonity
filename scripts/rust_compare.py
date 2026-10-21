import json,sys
a=json.load(open(sys.argv[1])); b=json.load(open(sys.argv[2]))
bad=0
for sid in sorted(b):
    ex={s['step']:s for s in a[sid]['steps']}
    got={s['step']:s for s in b[sid]['steps']}
    for n in sorted(ex):
        if n not in got: print(sid,n,'нет шага'); bad+=1; continue
        for k in ('methods','calls','remote','data','journal'):
            if ex[n][k]!=got[n][k]:
                bad+=1
                if k=='journal':
                    ks=set(ex[n][k])|set(got[n][k])
                    d=[x for x in sorted(ks) if ex[n][k].get(x)!=got[n][k].get(x)]
                    print(sid,n,k,len(d),'ключей различаются; пример:',d[:2])
                else:
                    e=set(map(json.dumps,ex[n][k])); g=set(map(json.dumps,got[n][k]))
                    print(sid,n,k,'лишних',len(g-e),'пропущено',len(e-g),'|',sorted(g-e)[:2],sorted(e-g)[:2])
print('расхождений',bad)
