"""Prepare homework 2 corpus from homework 1 question JSONL.
Run: python prepare_hw2_data.py --input 'fresh(1).jsonl'
Network required only while fetching sources. No LLM calls.
"""
import argparse, json, re, time
from collections import Counter
from pathlib import Path
from urllib.parse import quote, urlparse
import requests
from bs4 import BeautifulSoup

API='https://en.wikipedia.org/w/api.php'
HEADERS={'User-Agent':'RAG-education-course/1.0 (academic exercise; contact course organizers)'}

def normalized(s):
    return ' '.join(re.findall(r'\w+',str(s).casefold(),flags=re.U))

def has_evidence(text, evidence):
    a,b=normalized(text),normalized(evidence)
    # Exact normalized quote prevents silently admitting unsupported questions.
    return bool(b) and b in a

def wiki_extract(title,session):
    params={'action':'query','prop':'extracts','explaintext':1,'titles':title,'redirects':1,'format':'json'}
    resp=session.get(API,params=params,timeout=50,headers=HEADERS)
    resp.raise_for_status()
    page=next(iter(resp.json()['query']['pages'].values()))
    return page.get('title',title),page.get('extract','')

def official_extract(url,session):
    resp=session.get(url,timeout=50,headers=HEADERS);resp.raise_for_status()
    soup=BeautifulSoup(resp.text,'html.parser')
    for tag in soup(['script','style','nav','footer','header','noscript']):tag.decompose()
    main=soup.find('main') or soup.find('article') or soup
    parts=[]
    for tag in main.find_all(['h1','h2','h3','h4','p','li']):
        t=' '.join(tag.get_text(' ',strip=True).split())
        if len(t)>35:parts.append(t)
    return '\n'.join(parts)

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--input',default='fresh(1).jsonl');ap.add_argument('--output',default='data');a=ap.parse_args()
    out=Path(a.output);out.mkdir(parents=True,exist_ok=True)
    questions=[json.loads(x) for x in Path(a.input).read_text(encoding='utf-8').splitlines() if x.strip()]
    assert all(all(t.get(k) for k in ('id','question','answer','evidence','page','url')) for t in questions)
    grouped={}
    for t in questions:grouped.setdefault((t['page'],t['url']),[]).append(t)
    docs=[]; missing=[];session=requests.Session()
    for (page,url),items in grouped.items():
        try:
            host=urlparse(url).hostname or ''
            if host in ('en.wikipedia.org','www.wikipedia.org'):
                title,body=wiki_extract(page,session)
            elif host in ('openai.com','www.openai.com','blog.google','ai.google.dev','ai.meta.com','blog.google.com'):
                title,body=page,official_extract(url,session)
            else:
                raise ValueError('unsupported source domain: '+host)
            if not body.strip():raise ValueError('empty article')
            docs.append({'page':page,'url':url,'text':body,'original_title':title})
            coverage=sum(has_evidence(body,q['evidence']) for q in items)
            print(f'{page:40.40s} text={len(body):7d}, supported={coverage}/{len(items)}')
        except (requests.RequestException,ValueError,KeyError) as e:
            print('FAILED',page,str(e)[:140]);missing.append({'page':page,'error':str(e)})
        time.sleep(.15)
    by_page={d['page']:d['text'] for d in docs}
    supported=[q for q in questions if has_evidence(by_page.get(q['page'],''),q['evidence'])]
    unsupported=[{'id':q['id'],'page':q['page'],'question':q['question'],'reason':'quote absent from retrieved document'}
                 for q in questions if q not in supported]
    for fn,items in [('corpus_2026.jsonl',docs),('fresh_2026.jsonl',supported),('unsupported_questions.jsonl',unsupported)]:
        (out/fn).write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in items),encoding='utf-8')
    nlines=sum(1 for d in docs for ln in d['text'].splitlines() if len(ln.strip())>40)
    nchars=sum((len(' '.join(d['text'].split()))+399)//400 for d in docs)
    stats={'questions_original':len(questions),'sources_attempted':len(grouped),'sources_retrieved':len(docs),
           'supported_questions':len(supported),'unsupported_questions':len(unsupported),
           'estimated_line_chunks':nlines,'estimated_char_chunks':nchars,'fetch_errors':missing,
           'question_ids_supported':[q['id'] for q in supported]}
    (out/'coverage.json').write_text(json.dumps(stats,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in stats.items() if k not in ('fetch_errors','question_ids_supported')},ensure_ascii=False,indent=2))
    if len(supported)<30 or min(nlines,nchars)<300:
        print('WARNING: corpus does not yet meet homework requirements; inspect coverage.json')
if __name__=='__main__':main()
