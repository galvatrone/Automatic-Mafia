import argparse, json
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT))
from app import Model
from shared.exchange import read_participants

def main():
    parser=argparse.ArgumentParser(); parser.add_argument("--participants-file",default=str(ROOT/"person_face/results/verification/participants.json")); args=parser.parse_args(); path=Path(args.participants_file); participants=read_participants(path); model=Model(participants)
    for person_id in model.people: model.click(person_id)
    model.click(next(iter(model.people))); valid,message=model.validate(); confirmed,_=model.confirm()
    report={"exchange_loaded":True,"participant_count":len(participants),"cycle_valid":valid,"numbers_confirmed":confirmed,"numbers":{key:value.player_number for key,value in model.people.items()},"message":message}
    target=Path(__file__).parent/"results/verification.json"; target.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8"); print(json.dumps(report,ensure_ascii=False,indent=2))
if __name__=="__main__": main()
