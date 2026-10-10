"""Run with a live server: python -m scripts.demo_quote [--url http://127.0.0.1:8000]."""
import argparse
import json
import httpx

COMPLETE = '12 pcs 304 stainless steel sheet 0.060 in 48 x 96 in\n5 pcs A36 carbon steel plate 0.25 in 48 x 96 in'
AMBIGUOUS = '20 pcs 304 SS sheet 16ga 4x8'

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--url',default='http://127.0.0.1:8000')
    args=parser.parse_args()
    with httpx.Client(base_url=args.url,timeout=180) as client:
        for label,text in [('A: complete',COMPLETE),('B: ambiguous',AMBIGUOUS)]:
            response=client.post('/api/quote/run',json={'text':text})
            response.raise_for_status()
            result=response.json()
            print(label,json.dumps(result,indent=2))
            if label.startswith('B'):
                response=client.post('/api/quote/clarify',json={'rfq_id':result['rfq_id'],'answers':[{'line_id':'LINE-001','field':k,'value':v} for k,v in [('thickness','0.060 in'),('width','48 in'),('length','96 in')]]})
                response.raise_for_status()
                print('B: resumed',json.dumps(response.json(),indent=2))

if __name__=='__main__':main()
