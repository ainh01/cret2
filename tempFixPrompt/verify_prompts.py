import asyncio, json, os, sys, difflib

ROOT = r'C:\Users\Ainh\Desktop\fakedev\cret2'
os.chdir(ROOT)
sys.path.insert(0, ROOT)
import app

DIR = os.path.join(ROOT, 'tempFixPrompt', 'needtofix')
CAP = {}

USER_INPUT = 'ZZUSERINPUTZZ'


def record(tag, prompt):
    CAP.setdefault(tag, []).append(prompt)


SCHEMA_REPLY = '{"concepts": [], "uncertainties": [], "outline": ["a"]}'
ONE_Q = [{'id': 1, 'question': 'Q?',
          'options': [{'label': 'right', 'value': 'A'}, {'label': 'w', 'value': 'B'},
                      {'label': 'w2', 'value': 'C'}, {'label': 'w3', 'value': 'D'}],
          'correct': 'A', 'explanation': 'E'}]


async def fake_ai(prompt, images=None):
    if prompt.startswith('STAGE: KNOWLEDGE'):
        record('knowledge', prompt)
        return SCHEMA_REPLY
    if prompt.startswith('STAGE: CREATE'):
        record('create', prompt)
        return '```material\nZZDRAFTZZ\nendmaterial```'
    if prompt.startswith('ZZTEMPLATEZZ'):
        record('enrich', prompt)
        return '```material\nZZENRICHEDZZ\nendmaterial```'
    if prompt.startswith('STAGE: SOURCE REVIEW MATERIAL'):
        record('review_material', prompt)
        return app.REVIEW_MATERIAL_BEGIN + '\nZZCHECKEDZZ\n' + app.REVIEW_MATERIAL_END
    if prompt.startswith('STAGE: SOURCE REVIEW QUIZ'):
        record('review_quiz', prompt)
        return (app.REVIEW_QUIZ_BEGIN + '\n' + json.dumps(ONE_Q) + '\n' + app.REVIEW_QUIZ_END)
    if prompt.startswith('Bạn là chuyên gia'):
        record('planner', prompt)
        return json.dumps([{'section': 0, 'prompt': 'ZZPROMPTZZ', 'alt': 'ZZALTZZ'}])
    raise AssertionError('unexpected prompt: ' + prompt[:90])


CFG = {'quiz_frontend_base': 'https://vtask.fun', 'quiz_backend_base': 'https://api.vtask.fun',
       'randomize': False,
       'steps': {'material': {'enabled': True, 'template': 'ZZTEMPLATEZZ'},
                 'quiz': {'enabled': False, 'template': ''},
                 'interactive': {'enabled': False, 'template': ''}}}


async def fake_share(cfg, state):
    return 'https://vtask.fun/abcdef'


async def capture_all():
    app.ai_call = fake_ai
    app.load_config = lambda: CFG
    app.share_state = fake_share
    await app.run_pipeline(asyncio.Queue(), USER_INPUT, question_count=6)

    # 05: rerun review with a schema + one question so the quiz prompt path fires
    await app.review_material_and_quiz(app.source_context(USER_INPUT, ''), SCHEMA_REPLY,
                                       'ZZMATERIALZZ', ONE_Q, None)

    # 06: planner
    planner_material = ('Đoạn một đủ dài để được chọn làm mục minh họa.\n\n'
                        'Đoạn hai cũng đủ dài để được chọn làm mục minh họa.\n')
    await app.illustration_plan(planner_material)
    CAP['planner_material'] = [planner_material]

    # 07: image wrapper
    async def fake_gen(prompt):
        record('wrapper', prompt)
        raise RuntimeError('capture only')
    app.generated_image_bytes = fake_gen
    await app.generate_and_insert('Body.\n', [(0, None, 'ZZPROMPTZZ', 'ZZALTZZ')],
                                  'https://example.com', replace=False)

    # 09: ASCII path with a block the detector accepts
    art = '┌───┐\n│ A │\n└───┘\n'
    _, diagrams = app.prepare_diagram_replacements('Trước.\n\n' + art + '\nSau.\n')
    CAP['diagram_blocks'] = [len(diagrams), [t for _s, _e, t in diagrams]]
    await app.add_illustration('Trước.\n\n' + art + '\nSau.\n', 'https://example.com')
    CAP['ascii_prompt'] = [CAP['wrapper'][-1], art.strip()]

    # 08: fallback
    CAP['fallback'] = []
    for end, text, alt in app.fallback_illustration_plans([(9, 'ZZSECTIONTEXTZZ', 'H')]):
        CAP['fallback'].append(text)

    CAP['label'] = [app.REFERENCE_PROMPT_LABEL]


def read(name):
    with open(os.path.join(DIR, name), encoding='utf-8', newline='') as fh:
        return fh.read()


def fill(name, mapping):
    raw = read(name)
    for key, value in mapping.items():
        raw = raw.replace('{{' + key + '}}', value)
    left = [seg for seg in raw.split('{{')[1:]]
    assert not left, 'unfilled placeholder in ' + name + ': ' + str(left[:2])
    return raw[:-1] if raw.endswith('\n') else raw


def compare(name, got, expected, note=''):
    ok = got == expected
    print(('PASS  ' if ok else 'FAIL  ') + name + (('  ' + note) if note else ''))
    if not ok:
        diff = list(difflib.unified_diff(got.splitlines(True), expected.splitlines(True),
                                         'file' + ('  ' + note if note else ''), 'real prompt'))
        for line in diff[:50]:
            print('    ' + line.rstrip('\n'))
    return ok


async def run():
    await capture_all()
    results = []

    context = app.source_context(USER_INPUT, '')
    schema = app.schema_text(app.schema_from_reply(SCHEMA_REPLY))
    gp = app.GROUNDING_POLICY

    results.append(compare('01_knowledge_schema.txt', fill('01_knowledge_schema.txt',
                       {'GROUNDING_POLICY': gp, 'CONTEXT': context}), CAP['knowledge'][0]))
    results.append(compare('02_create_material.txt', fill('02_create_material.txt',
                       {'GROUNDING_POLICY': gp, 'SCHEMA': schema, 'CONTEXT': context}),
                       CAP['create'][0]))

    enrich = CAP['enrich'][0]
    prefix = 'ZZTEMPLATEZZ\n\n'
    assert enrich.startswith(prefix), enrich[:60]
    results.append(compare('03_enrich_draft.txt', fill('03_enrich_draft.txt',
                       {'GROUNDING_POLICY': gp, 'DRAFT': 'ZZDRAFTZZ', 'SCHEMA': schema,
                        'CONTEXT': context}), enrich[len(prefix):],
                       'after the configure.json template'))

    results.append(compare('04_review_material.txt', fill('04_review_material.txt',
                       {'GROUNDING_POLICY': gp, 'CONTEXT': context, 'SCHEMA': schema,
                        'MATERIAL': 'ZZENRICHEDZZ'}), CAP['review_material'][0]))

    results.append(compare('05_review_quiz.txt', fill('05_review_quiz.txt',
                       {'GROUNDING_POLICY': gp, 'CONTEXT': context, 'SCHEMA': schema,
                        'CHECKED_MATERIAL': 'ZZCHECKEDZZ',
                        'QUESTIONS_JSON': json.dumps(ONE_Q, ensure_ascii=False)}),
                       CAP['review_quiz'][0]))

    material = CAP['planner_material'][0]
    sections = app.illustration_sections(material)
    choices = '\n'.join(f'{i} [heading: {h or "(none)"}]: {t[:350]}'
                        for i, (_e, t, h) in enumerate(sections))
    results.append(compare('06_illustration_planner.txt', fill('06_illustration_planner.txt',
                       {'MAX_ILLUSTRATIONS': str(app.MAX_ILLUSTRATIONS),
                        'NUMBERED_SECTIONS': choices, 'MATERIAL_HEAD': material[:16000]}),
                       CAP['planner'][0]))

    results.append(compare('07_image_generation_wrapper.txt', fill('07_image_generation_wrapper.txt',
                       {'PROMPT': 'ZZPROMPTZZ'}), CAP['wrapper'][0]))

    results.append(compare('08_illustration_fallback.txt', fill('08_illustration_fallback.txt',
                       {'SECTION_TEXT_HEAD': 'ZZSECTIONTEXTZZ'}), CAP['fallback'][0]))

    # 09 is the inner text; the image API sees wrapper-with-block
    nine = read('09_ascii_diagram_replacement.txt')
    nine = nine[:-1] if nine.endswith('\n') else nine
    composed = fill('07_image_generation_wrapper.txt', {'PROMPT': CAP['ascii_prompt'][1]})
    results.append(compare('09_ascii_diagram_replacement.txt', composed, CAP['ascii_prompt'][0],
                           'composed through 07'))

    ten = read('10_reference_prompt_label.txt')
    ten = ten[:-1] if ten.endswith('\n') else ten
    results.append(compare('10_reference_prompt_label.txt', ten, CAP['label'][0]))

    print('\n%d/%d match the code exactly' % (sum(1 for r in results if r), len(results)))
    print('diagram blocks detected for the 09 test art: %d' % CAP['diagram_blocks'][0])


asyncio.run(run())
