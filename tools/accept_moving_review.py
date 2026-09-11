"""Record an explicit human visual-review selection; all others stay unused."""
import argparse,json
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('folder',type=Path);p.add_argument('--positive',required=True);p.add_argument('--negative',required=True);a=p.parse_args()
positive={int(v) for v in a.positive.split(',') if v};negative={int(v) for v in a.negative.split(',') if v};assert not positive&negative
rows=list(map(json.loads,(a.folder/'pending.jsonl').read_text(encoding='utf-8').splitlines()));assert positive|negative <= {r['index'] for r in rows}
accepted=[]
for r in rows:
    if r['index'] not in positive|negative:continue
    r.update(review_status='accepted',reviewer='Codex manual visual inspection',review_evidence=f'Inspected complete 96px crop in review-{r["index"]//36}.png; '+('physical vehicle and box manually confirmed, class from controlled fixture type' if r['index'] in positive else 'background only, no physical vehicle anywhere in the crop'))
    if r['index'] in negative:r['boxes']=[]
    accepted.append(r)
(a.folder/'accepted.jsonl').write_text('\n'.join(json.dumps(r,ensure_ascii=False) for r in accepted),encoding='utf-8')
(a.folder/'review-decisions.json').write_text(json.dumps(dict(positive=sorted(positive),negative=sorted(negative),unused=len(rows)-len(accepted)),indent=2),encoding='utf-8')
print('accepted vehicles',len(positive),'backgrounds',len(negative),'unused',len(rows)-len(accepted))
