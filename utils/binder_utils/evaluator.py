import re
from dateutil.parser import parse

from ..binder_utils.normalizer import str_normalize
from ..binder_utils.wtq.evaluator import to_value_list, check_denotation
from ..binder_utils.mmqa.evaluator import acc
from dateutil import parser

WEEKDAY_DIC = {
    'friday': True,
    'fri.': True,
    'fri': True,
    'monday': True,
    'mon.': True,
    'mon': True,
    'saturday': True,
    'sat.': True,
    'sat': True,
    'sunday': True,
    'sun.': True,
    'sun': True,
    'thursday': True,
    'thu.': True,
    'thu': True,
    'tuesday': True,
    'tue.': True,
    'tue': True,
    'wednesday': True,
    'wed.': True,
    'wed': True,
}

def my_date(value, format="%Y-%m-%d %H:%M:%S"):
    value = str(value)

    if len(value) <= 4:
        if "th" in value or "st" in value or "rd" in value or "nd" in value:
            raise ValueError(f"Cannot convert {value} to date")

    if value.lower().strip() in WEEKDAY_DIC:
        raise ValueError(f"Cannot convert {value} to date")

    if value.count("-") == 1:
        fir, sec = value.split("-")
        if str(fir) == str(int(fir)) and str(sec) == str(int(sec)):
            raise ValueError(f"Cannot convert {value} to date")

    try:
        # 
        date_obj = parser.parse(value)
        # if CURRENT_YEAR in ret:
        #     ret = ret.replace(CURRENT_YEAR, DATASET_YEAR)
        return date_obj

    except ValueError:
        raise ValueError(f"Cannot convert {value} to date")


def is_date(value):
    
    try:
        my_date(value)
        return True
    except ValueError:
        return False


def is_float(value):
    try:
        my_float(value)
        return True
    except ValueError:
        return False


def my_float(value):
    if value == "nan":
        raise ValueError(f"Cannot convert {value} to float")
    try:
        value = str(value).replace(",", "")
        if (
            value.endswith("st")
            or value.endswith("nd")
            or value.endswith("rd")
            or value.endswith("th")
        ):
            value = value[:-2].strip()

        ret = float(value)
        # if ret is integer
        if ret.is_integer():
            return int(ret)
        else:
            return ret
    except ValueError:
        raise ValueError(f"Cannot convert {value} to float")

class Evaluator:
    def __init__(self):
        pass

    def evaluate(
            self,
            pred_answer,
            gold_answer,
            dataset,
            allow_semantic=True,
            question=None
    ):
        if dataset == 'wikitq':
            return self.eval_ex_match(pred_answer, gold_answer, allow_semantic, question)
        elif dataset == 'tab_fact':
            return self.eval_tabfact_match(pred_answer, gold_answer)
        elif dataset == 'mmqa':
            # For more metrics on MMQA,
            # please use the utils/mmqa/eval_mmqa.py to call official on all prediction data
            return self.eval_mmqa_match(pred_answer, gold_answer)
        else:
            raise ValueError(f'{dataset} evaluator is not supported.')

    def eval_ex_match(self, pred, gold, allow_semantic=True, question=None):
        if not isinstance(pred, list):
            pred = [pred]
            gold = [gold]

        pred = [str(p).lower().replace('<br>', ' ').strip() for p in pred]
        gold = [str(g).lower().strip() for g in gold]

        if not allow_semantic:
            # WikiTQ eval w. string normalization using recognizer
            pred = [str_normalize(span) for span in pred]
            gold = [str_normalize(span) for span in gold]
            pred = to_value_list(pred)
            gold = to_value_list(gold)
            return check_denotation(pred, gold)
        else:
            assert isinstance(question, str)
            question = re.sub('\s+', ' ', question).strip().lower()
            pred = [str_normalize(span) for span in pred]
            gold = [str_normalize(span) for span in gold]
            pred = sorted(list(set(pred)))
            gold = sorted(list(set(gold)))
            # (1) 0 matches 'no', 1 matches 'yes'; 0 matches 'more', 1 matches 'less', etc.
            if len(pred) == 1 and len(gold) == 1:
                if (pred[0] == '0' and gold[0] == 'no') \
                        or (pred[0] == '1' and gold[0] == 'yes'):
                    return True
                question_tokens = question.split()
                try:
                    pos_or = question_tokens.index('or')
                    token_before_or, token_after_or = question_tokens[pos_or - 1], question_tokens[pos_or + 1]
                    if (pred[0] == '0' and gold[0] == token_after_or) \
                            or (pred[0] == '1' and gold[0] == token_before_or):
                        return True
                except Exception as e:
                    pass
            # (2) Number value (allow units) and Date substring match
            if len(pred) == 1 and len(gold) == 1:
                NUMBER_UNITS_PATTERN = re.compile('^\$*[+-]?([0-9]*[.])?[0-9]+(\s*%*|\s+\w+)$')
                DATE_PATTERN = re.compile('[0-9]{4}-[0-9]{1,2}-[0-9]{1,2}\s*([0-9]{1,2}:[0-9]{1,2}:[0-9]{1,2})?')
                DURATION_PATTERN = re.compile('(P|PT)(\d+)(Y|M|D|H|S)')
                p, g = pred[0], gold[0]
                #! add Season match: 1915-16 equals to 1915-1916
                if '-' in g and '-' in p and len(g.split('-')) == 2 and len(p.split('-')) == 2:
                    g_start, g_end = g.split('-')
                    p_start, p_end = p.split('-')
                    if is_float(g_start) and is_float(g_end) and is_float(p_start) and is_float(p_end) \
                        and g_start == p_start:

                        if len(g_end) == 2 and len(p_end) == 4:
                            if int(g_start[2:]) < int(g_end):
                                g_end = g_start[:2] + g_end
                            else:
                                g_end = str(int(g_start[:2]) + 1) + g_end
                        if g_end == p_end:
                            return True

                # Restore `duration` type, e.g., from 'P3Y' -> '3'
                if re.match(DURATION_PATTERN, p):
                    p = re.match(DURATION_PATTERN, p).group(2)
                if re.match(DURATION_PATTERN, g):
                    g = re.match(DURATION_PATTERN, g).group(2)
                match = False
                num_flag, date_flag = False, False
                # Number w. unit match after string normalization.
                # Either pred or gold being number w. units suffices it.
                if re.match(NUMBER_UNITS_PATTERN, p) or re.match(NUMBER_UNITS_PATTERN, g):
                    num_flag = True
                # Date match after string normalization.
                # Either pred or gold being date suffices it.
                if re.match(DATE_PATTERN, p) or re.match(DATE_PATTERN, g):
                    date_flag = True
                if num_flag:
                    p_set, g_set = set(p.split()), set(g.split())
                    if p_set.issubset(g_set) or g_set.issubset(p_set):
                        match = True
                if date_flag:
                    if is_date(p) and is_date(g):
                        p = parse(p).strftime('%Y-%m-%d %H:%M:%S')
                        g = parse(g).strftime('%Y-%m-%d %H:%M:%S')
                    p_set, g_set = set(p.replace('-', ' ').split()), set(g.replace('-', ' ').split())
                    if p_set.issubset(g_set) or g_set.issubset(p_set):
                        match = True
                if match:
                    return True
            pred = to_value_list(pred)
            gold = to_value_list(gold)
            return check_denotation(pred, gold)

    def eval_tabfact_match(self, pred, gold):
        if isinstance(pred, list):
            pred = pred[0]
        if isinstance(gold, list):
            gold = gold[0]
        pred, gold = str(pred), str(gold)
        return pred == gold

    def eval_mmqa_match(self, pred_answer, gold_answer):
        return acc(pred_answer, gold_answer)
