import json, os, sys, itertools
from glob import glob
from copy import deepcopy

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')
SCORING = [1, 2, 3, 5, 8, 13]
REGION_KEYS = ['east', 'south', 'west', 'midwest']

# Manual overrides: our tournament.json name -> KenPom name
KENPOM_NAME_MAP = {
    'UConn':    'Connecticut',
    'MICHST':   'Michigan St.',
    'Iowa St.': 'Iowa State',
    'St. John\'s': 'St. John\'s (NY)',
    'Utah St.': 'Utah State',
    'Texas A&M': 'Texas A&M',
}

# ── Data loading ──────────────────────────────────────────────────────────────

def load_json(path):
    with open(path, encoding='utf-8') as f:
        return json.load(f)

def load_kenpom():
    """
    Finds the most recent KenPom xlsx in the repo root. Returns:
      { team_name: pythagorean_win_pct }
    Pythagorean formula: ORtg^11.5 / (ORtg^11.5 + DRtg^11.5)
    KenPom xlsx columns: B=team+seed, F=ORtg, H=DRtg (0-indexed: 1, 5, 7)
    """
    try:
        import openpyxl
    except ImportError:
        print('WARNING: openpyxl not installed. Run: pip install openpyxl')
        return None

    xlsx_files = [f for f in glob(os.path.join(os.path.dirname(os.path.abspath(__file__)), '*.xlsx'))
                  if not os.path.basename(f).startswith('~')]
    if not xlsx_files:
        print('WARNING: No KenPom xlsx found in repo root. KenPom simulation skipped.')
        return None

    xlsx_path = max(xlsx_files, key=os.path.getmtime)
    print('KenPom source: ' + os.path.basename(xlsx_path))

    wb = openpyxl.load_workbook(xlsx_path, data_only=True)
    ws = wb.active
    kenpom = {}
    for row in ws.iter_rows(min_row=3, values_only=True):
        if row[0] is None:
            continue
        raw = str(row[1]).replace('\xa0', ' ').strip()
        # Strip trailing seed number if present
        parts = raw.rsplit(' ', 1)
        name = parts[0].strip() if len(parts) == 2 and parts[1].isdigit() else raw
        try:
            ortg, drtg = float(row[5]), float(row[7])
        except (TypeError, ValueError):
            continue
        if ortg and drtg:
            pyth = (ortg ** 11.5) / (ortg ** 11.5 + drtg ** 11.5)
            kenpom[name] = pyth

    # Apply name map overrides
    for our_name, kenpom_name in KENPOM_NAME_MAP.items():
        if kenpom_name in kenpom:
            kenpom[our_name] = kenpom[kenpom_name]

    return kenpom

# ── Scoring helpers ───────────────────────────────────────────────────────────

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

# ── Simulation mechanics ──────────────────────────────────────────────────────

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

def get_contestants(sim, slot):
    """Return (teamA, teamB) for an undecided slot given current sim state."""
    if slot['type'] == 'region':
        key, rd, idx = slot['region'], slot['round'], slot['index']
        rr = sim['results'][key]
        if rd == 'round2':
            return rr['round1'][idx * 2]['winner'], rr['round1'][idx * 2 + 1]['winner']
        elif rd == 'sweet16':
            return rr['round2'][idx * 2]['winner'], rr['round2'][idx * 2 + 1]['winner']
        elif rd == 'elite8':
            return rr['sweet16'][0]['winner'], rr['sweet16'][1]['winner']
    else:
        ff_slot = slot['ff_slot']
        sm = sim['final_four']
        rr = sim['results']
        if ff_slot == 'semifinal1':
            return rr['east']['elite8']['winner'], rr['south']['elite8']['winner']
        elif ff_slot == 'semifinal2':
            return rr['west']['elite8']['winner'], rr['midwest']['elite8']['winner']
        elif ff_slot == 'championship':
            return sm['semifinal1']['winner'], sm['semifinal2']['winner']

def apply_outcome(sim, slot, winner, loser):
    game = {'winner': winner, 'loser': loser, 'score': None, 'status': 'final'}
    if slot['type'] == 'region':
        key, rd, idx = slot['region'], slot['round'], slot['index']
        if rd == 'elite8':
            sim['results'][key]['elite8'] = game
        else:
            sim['results'][key][rd][idx] = game
    else:
        sim['final_four'][slot['ff_slot']] = game

def log5(pA, pB):
    """P(A beats B) given Pythagorean win percentages."""
    denom = pA + pB - 2 * pA * pB
    if denom == 0:
        return 0.5
    return (pA - pA * pB) / denom

def get_win_prob(teamA, teamB, kenpom):
    if kenpom is None or teamA not in kenpom or teamB not in kenpom:
        return 0.5
    return log5(kenpom[teamA], kenpom[teamB])

ROUND_LABELS = {
    'sweet16': 'wins Sweet 16',
    'elite8': 'wins region',
    'semifinal1': 'wins Final Four',
    'semifinal2': 'wins Final Four',
    'championship': 'wins Championship',
}

def get_picks_for_slot(picks, slot):
    """Return the team this participant picked for a given undecided slot."""
    if slot['type'] == 'region':
        key, rd, idx = slot['region'], slot['round'], slot['index']
        pr = picks['regions'][key]
        if rd == 'elite8':
            return pr['elite8']
        return pr[rd][idx]
    else:
        ff_slot = slot['ff_slot']
        pff = picks['final_four']
        if ff_slot == 'semifinal1':
            return pff['east_south_winner']
        elif ff_slot == 'semifinal2':
            return pff['west_midwest_winner']
        elif ff_slot == 'championship':
            return picks['champion']

ROUND_DEPTH = {
    'sweet16': 0, 'elite8': 1,
    'semifinal1': 2, 'semifinal2': 2,
    'championship': 3,
}

def describe_path(sim_results, undecided, picks):
    """Describe the outcomes that match this participant's picks (the wins they need).
    Deduplicates per team (keeps deepest run only) and orders deepest first."""
    # Collect all matching picks with their round depth
    team_best = {}  # team -> (depth, label)
    for slot in undecided:
        pick = get_picks_for_slot(picks, slot)
        if slot['type'] == 'region':
            key, rd, idx = slot['region'], slot['round'], slot['index']
            if rd == 'elite8':
                winner = sim_results['results'][key]['elite8']['winner']
            else:
                winner = sim_results['results'][key][rd][idx]['winner']
            round_key = rd
        else:
            ff_slot = slot['ff_slot']
            winner = sim_results['final_four'][ff_slot]['winner']
            round_key = ff_slot

        if winner == pick:
            depth = ROUND_DEPTH.get(round_key, -1)
            label = ROUND_LABELS.get(round_key, round_key)
            if pick not in team_best or depth > team_best[pick][0]:
                team_best[pick] = (depth, label)

    if not team_best:
        return None
    # Sort by depth descending (deepest run first)
    sorted_teams = sorted(team_best.items(), key=lambda x: -x[1][0])
    return ', '.join(team + ' ' + label for team, (depth, label) in sorted_teams)

def count_final_games(results):
    count = 0
    for key in REGION_KEYS:
        rr = results['results'][key]
        for rd, size in [('round1', 8), ('round2', 4), ('sweet16', 2)]:
            for i in range(size):
                g = rr[rd][i]
                if g and g['status'] == 'final':
                    count += 1
        g = rr['elite8']
        if g and g['status'] == 'final':
            count += 1
    ff = results['final_four']
    for slot in ('semifinal1', 'semifinal2', 'championship'):
        g = ff[slot]
        if g and g['status'] == 'final':
            count += 1
    return count

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    results = load_json(os.path.join(DATA_DIR, 'results.json'))
    pick_files = sorted(glob(os.path.join(DATA_DIR, 'picks', '*.json')))
    all_picks = [load_json(p) for p in pick_files]
    names = [p['participant'] for p in all_picks]

    kenpom = load_kenpom()

    # --check-names: verify alive teams resolve in KenPom data
    if '--check-names' in sys.argv:
        # Alive teams = all R2 winners (they are the Sweet 16 field)
        alive = set()
        for key in REGION_KEYS:
            rr = results['results'][key]
            for i in range(4):
                g = rr['round2'][i]
                if g and g['status'] == 'final':
                    alive.add(g['winner'])
        print('\nName check against KenPom:')
        for team in sorted(alive):
            status = 'OK  ' if (kenpom and team in kenpom) else '??  '
            print(status + team)
        sys.exit(0)

    base_scores = {p['participant']: score_picks(results, p) for p in all_picks}
    undecided = build_undecided(results)
    n = len(undecided)
    total_scenarios = 2 ** n
    final_count = count_final_games(results)

    print('Games complete: {}  |  Remaining: {}  |  Scenarios: {:,}'.format(
        final_count, n, total_scenarios))

    win_flat    = {name: 0   for name in names}
    win_kenpom  = {name: 0.0 for name in names}
    place_flat  = {name: 0   for name in names}
    place_kenpom = {name: 0.0 for name in names}
    ev_flat     = {name: 0.0 for name in names}
    ev_kenpom   = {name: 0.0 for name in names}
    best_path   = {name: (0.0, None) for name in names}  # (prob, sim_state)
    beat_sammy  = {name: 0.0 for name in names}  # KenPom-weighted prob of beating Sammy

    for bits in itertools.product(range(2), repeat=n):
        sim = deepcopy(results)
        scenario_prob = 1.0

        for i, slot in enumerate(undecided):
            a, b = get_contestants(sim, slot)
            if bits[i] == 0:
                winner, loser = a, b
                p = get_win_prob(a, b, kenpom)
            else:
                winner, loser = b, a
                p = get_win_prob(b, a, kenpom)
            apply_outcome(sim, slot, winner, loser)
            scenario_prob *= p

        scores = {p['participant']: score_picks(sim, p) for p in all_picks}
        sorted_unique = sorted(set(scores.values()), reverse=True)
        max_score = sorted_unique[0]
        second_score = sorted_unique[1] if len(sorted_unique) > 1 else max_score

        first_place  = [nm for nm, s in scores.items() if s == max_score]
        second_place = [nm for nm, s in scores.items() if s == second_score and s < max_score]

        for nm in first_place:
            win_flat[nm]   += 1
            win_kenpom[nm] += scenario_prob
            place_flat[nm]  += 1
            place_kenpom[nm] += scenario_prob

        for nm in second_place:
            place_flat[nm]  += 1
            place_kenpom[nm] += scenario_prob

        # Prize distribution: 1st=$75, 2nd=$25
        if not second_place:
            # Everyone tied for 1st splits the full $100
            share = 100.0 / len(first_place)
            for nm in first_place:
                ev_flat[nm]   += share
                ev_kenpom[nm] += scenario_prob * share
        else:
            first_share = 75.0 / len(first_place)
            second_share = 25.0 / len(second_place)
            for nm in first_place:
                ev_flat[nm]   += first_share
                ev_kenpom[nm] += scenario_prob * first_share
            for nm in second_place:
                ev_flat[nm]   += second_share
                ev_kenpom[nm] += scenario_prob * second_share

        # Track best (most likely) path to the money for each participant
        in_money = set(first_place) | set(second_place)
        for nm in in_money:
            if scenario_prob > best_path[nm][0]:
                best_path[nm] = (scenario_prob, deepcopy(sim))

        # SOBS: who beats Sammy in this scenario?
        sammy_score = scores.get('Sammy', 0)
        for nm, s in scores.items():
            if s > sammy_score:
                beat_sammy[nm] += scenario_prob

    total_prob = sum(win_kenpom[nm] for nm in names) + sum(
        place_kenpom[nm] - win_kenpom[nm] for nm in names)
    # Normalization: use sum of scenario_probs via EV (always sums to $100)
    ev_kp_total = sum(ev_kenpom.values())
    # SOBS normalization: total probability mass = ev_kp_total / 100
    sobs_total_prob = ev_kp_total / 100.0 if ev_kp_total > 0 else 1.0

    sorted_names = sorted(names, key=lambda name: base_scores[name], reverse=True)
    if kenpom:
        print('\n{:<14} {:>7} {:>10} {:>12} {:>10} {:>10}'.format(
            'Participant', 'Score', 'Win%(50/50)', 'Win%(KenPom)', 'Place%KP', 'E[$$]KP'))
        print('-' * 70)
        for name in sorted_names:
            kp_win = 100.0 * win_kenpom[name] / ev_kp_total * 100 if ev_kp_total > 0 else 0
            kp_place = 100.0 * place_kenpom[name] / ev_kp_total * 100 if ev_kp_total > 0 else 0
            ev_dollars = ev_kenpom[name] / ev_kp_total * 100 if ev_kp_total > 0 else 0
            print('{:<14} {:>7} {:>9.1f}%  {:>10.1f}%  {:>8.1f}%   ${:>6.2f}'.format(
                name, base_scores[name],
                100.0 * win_flat[name] / total_scenarios,
                kp_win, kp_place, ev_dollars))
    else:
        print('\n{:<14} {:>7} {:>10}'.format('Participant', 'Score', 'Win%'))
        print('-' * 35)
        for name in sorted_names:
            print('{:<14} {:>7} {:>9.1f}%'.format(
                name, base_scores[name],
                100.0 * win_flat[name] / total_scenarios))

    sim_output = {
        'computed_at_game_count': final_count,
        'total_scenarios': total_scenarios,
        'has_kenpom': kenpom is not None,
        'participants': []
    }
    for p in all_picks:
        name = p['participant']
        pid = os.path.splitext(os.path.basename(pick_files[all_picks.index(p)]))[0]
        bp_prob, bp_sim = best_path[name]
        money_path = describe_path(bp_sim, undecided, p) if bp_sim else None
        entry = {
            'name': name,
            'pid': pid,
            'current_score': base_scores[name],
            'win_pct':    round(100.0 * win_flat[name]   / total_scenarios, 1),
            'place_pct':  round(100.0 * place_flat[name]  / total_scenarios, 1),
            'win_pct_kp':  round(100.0 * win_kenpom[name]  / ev_kp_total * 100, 1) if ev_kp_total > 0 else None,
            'place_pct_kp': round(100.0 * place_kenpom[name] / ev_kp_total * 100, 1) if ev_kp_total > 0 else None,
            'expected_winnings': round(ev_kenpom[name] / ev_kp_total * 100, 2) if ev_kp_total > 0 else None,
            'money_path': money_path,
            'sobs_pct': round(100.0 * beat_sammy[name] / sobs_total_prob, 1) if name != 'Sammy' else None,
        }
        sim_output['participants'].append(entry)

    out_path = os.path.join(DATA_DIR, 'results_sim.json')
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(sim_output, f, indent=2)
    print('\nWritten to: ' + out_path)

if __name__ == '__main__':
    main()
