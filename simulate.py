import json, os, itertools
from glob import glob
from copy import deepcopy

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')
SCORING = [1, 2, 3, 5, 8, 13]
REGION_KEYS = ['east', 'south', 'west', 'midwest']

def load_json(path):
    with open(path, encoding='utf-8') as f:
        return json.load(f)

def get_eliminated(results):
    elim = set()
    for key in REGION_KEYS:
        rr = results['results'][key]
        for rd, size in [('round1', 8), ('round2', 4), ('sweet16', 2)]:
            for i in range(size):
                g = rr[rd][i]
                if g and g['status'] == 'final' and g['loser']:
                    elim.add(g['loser'])
        g = rr['elite8']
        if g and g['status'] == 'final' and g['loser']:
            elim.add(g['loser'])
    ff = results['final_four']
    for slot in ('semifinal1', 'semifinal2', 'championship'):
        g = ff[slot]
        if g and g['status'] == 'final' and g['loser']:
            elim.add(g['loser'])
    return elim

def score_picks(results, picks):
    total = 0
    for key in REGION_KEYS:
        rr = results['results'][key]
        pr = picks['regions'][key]
        for i in range(8):
            g = rr['round1'][i]
            if g and g['status'] == 'final':
                if pr['round1'][i] == g['winner']: total += SCORING[0]
        for i in range(4):
            g = rr['round2'][i]
            if g and g['status'] == 'final':
                if pr['round2'][i] == g['winner']: total += SCORING[1]
        for i in range(2):
            g = rr['sweet16'][i]
            if g and g['status'] == 'final':
                if pr['sweet16'][i] == g['winner']: total += SCORING[2]
        g = rr['elite8']
        if g and g['status'] == 'final':
            if pr['elite8'] == g['winner']: total += SCORING[3]
    ff = results['final_four']
    pff = picks['final_four']
    g = ff['semifinal1']
    if g and g['status'] == 'final':
        if pff['east_south_winner'] == g['winner']: total += SCORING[4]
    g = ff['semifinal2']
    if g and g['status'] == 'final':
        if pff['west_midwest_winner'] == g['winner']: total += SCORING[4]
    g = ff['championship']
    if g and g['status'] == 'final':
        if picks['champion'] == g['winner']: total += SCORING[5]
    return total

def build_undecided(results):
    slots = []
    for key in REGION_KEYS:
        rr = results['results'][key]
        for rd, size in [('round2', 4), ('sweet16', 2)]:
            for i in range(size):
                if rr[rd][i] is None:
                    slots.append({'type': 'region', 'region': key, 'round': rd, 'index': i})
        if rr['elite8'] is None:
            slots.append({'type': 'region', 'region': key, 'round': 'elite8', 'index': None})
    ff = results['final_four']
    for slot in ('semifinal1', 'semifinal2', 'championship'):
        if ff[slot] is None:
            slots.append({'type': 'final_four', 'ff_slot': slot})
    return slots

def get_region_round_teams(sim, key, round_name, idx):
    rr = sim['results'][key]
    if round_name == 'round2':
        a = rr['round1'][idx * 2]['winner']
        b = rr['round1'][idx * 2 + 1]['winner']
    elif round_name == 'sweet16':
        a = rr['round2'][idx * 2]['winner']
        b = rr['round2'][idx * 2 + 1]['winner']
    elif round_name == 'elite8':
        a = rr['sweet16'][0]['winner']
        b = rr['sweet16'][1]['winner']
    return a, b

def get_ff_teams(sim, ff_slot):
    sm = sim['final_four']
    rr = sim['results']
    if ff_slot == 'semifinal1':
        return rr['east']['elite8']['winner'], rr['south']['elite8']['winner']
    elif ff_slot == 'semifinal2':
        return rr['west']['elite8']['winner'], rr['midwest']['elite8']['winner']
    elif ff_slot == 'championship':
        return sm['semifinal1']['winner'], sm['semifinal2']['winner']

def apply_outcome(sim, slot, bit):
    if slot['type'] == 'region':
        key, rd, idx = slot['region'], slot['round'], slot['index']
        a, b = get_region_round_teams(sim, key, rd, idx)
        winner, loser = (a, b) if bit == 0 else (b, a)
        game = {'winner': winner, 'loser': loser, 'score': None, 'status': 'final'}
        if rd == 'elite8':
            sim['results'][key]['elite8'] = game
        else:
            sim['results'][key][rd][idx] = game
    else:
        ff_slot = slot['ff_slot']
        a, b = get_ff_teams(sim, ff_slot)
        winner, loser = (a, b) if bit == 0 else (b, a)
        sim['final_four'][ff_slot] = {'winner': winner, 'loser': loser, 'score': None, 'status': 'final'}

def main():
    results = load_json(os.path.join(DATA_DIR, 'results.json'))
    pick_files = sorted(glob(os.path.join(DATA_DIR, 'picks', '*.json')))
    all_picks = [load_json(p) for p in pick_files]
    names = [p['participant'] for p in all_picks]

    base_scores = {p['participant']: score_picks(results, p) for p in all_picks}
    undecided = build_undecided(results)
    n = len(undecided)
    total_scenarios = 2 ** n

    # Count final games for staleness detection
    final_count = 0
    for key in REGION_KEYS:
        rr = results['results'][key]
        for rd, size in [('round1', 8), ('round2', 4), ('sweet16', 2)]:
            for i in range(size):
                g = rr[rd][i]
                if g and g['status'] == 'final':
                    final_count += 1
        g = rr['elite8']
        if g and g['status'] == 'final':
            final_count += 1
    ff = results['final_four']
    for slot in ('semifinal1', 'semifinal2', 'championship'):
        g = ff[slot]
        if g and g['status'] == 'final':
            final_count += 1

    print('Games complete: {}  |  Remaining: {}  |  Scenarios: {:,}'.format(final_count, n, total_scenarios))

    win_count  = {name: 0 for name in names}
    top2_count = {name: 0 for name in names}

    for bits in itertools.product(range(2), repeat=n):
        sim = deepcopy(results)
        for i, slot in enumerate(undecided):
            apply_outcome(sim, slot, bits[i])
        scores = {p['participant']: score_picks(sim, p) for p in all_picks}
        max_score = max(scores.values())
        sorted_scores = sorted(scores.values(), reverse=True)
        second_score = sorted_scores[1] if len(sorted_scores) > 1 else -1
        for name, s in scores.items():
            if s == max_score:
                win_count[name] += 1
            if s >= second_score:
                top2_count[name] += 1

    sorted_names = sorted(names, key=lambda name: base_scores[name], reverse=True)
    print('\n{:<14} {:>7} {:>10} {:>10}'.format('Participant', 'Score', 'Win%', 'Top2%'))
    print('-' * 45)
    for name in sorted_names:
        print('{:<14} {:>7} {:>9.1f}% {:>9.1f}%'.format(
            name, base_scores[name],
            100.0 * win_count[name] / total_scenarios,
            100.0 * top2_count[name] / total_scenarios))

    sim_output = {
        'computed_at_game_count': final_count,
        'total_scenarios': total_scenarios,
        'participants': []
    }
    for p in all_picks:
        name = p['participant']
        pid = os.path.splitext(os.path.basename(pick_files[all_picks.index(p)]))[0]
        sim_output['participants'].append({
            'name': name,
            'pid': pid,
            'current_score': base_scores[name],
            'win_pct': round(100.0 * win_count[name] / total_scenarios, 1),
            'top2_pct': round(100.0 * top2_count[name] / total_scenarios, 1)
        })

    out_path = os.path.join(DATA_DIR, 'results_sim.json')
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(sim_output, f, indent=2)
    print('\nWritten to: ' + out_path)

if __name__ == '__main__':
    main()
