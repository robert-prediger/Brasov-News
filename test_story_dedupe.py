import unittest
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch
from story_dedupe import deduplicate, tokens, StoryMatcher
from update_news import extract_headline, clean_headline, extract_metadata, extract_content_evidence


def article(title, slug, day='2026-10-26T12:00:00+02:00'):
    return {'title': title, 'url': 'https://example.com/' + slug,
            'source': 'Test', 'published': day}


class StoryDeduplicationTests(unittest.TestCase):
    def assert_grouped(self, first, second):
        result = deduplicate([first, second])
        self.assertEqual(len(result), 1)
        self.assertEqual(len(result[0]['coverage']), 2)

    def test_truncated_headline_and_synonyms(self):
        self.assert_grouped(
            article('Bărbat amendat pentru abandonarea câinilor la adăpost',
                    'barbat-amendat-abandonat-doi-caini-adapost-brasov'),
            article('S-a găsit făptașul! Amendă de 12.000 de lei...',
                    'amenda-aruncat-doi-catelusi-peste-gardul-adapostului-brasov'))

    def test_new_event_without_named_event_rule(self):
        self.assert_grouped(
            article('Biblioteca municipală inaugurează laboratorul digital pentru elevi',
                    'biblioteca-municipala-laborator-digital-elevi'),
            article('Laborator digital pentru elevi, inaugurat la biblioteca municipală',
                    'laborator-digital-elevi-biblioteca-municipala'))

    def test_word_forms_and_different_word_order(self):
        self.assert_grouped(
            article('Aur pentru sportivul Blănaru de la clubul Tadashi',
                    'aur-sportiv-blanaru-club-tadashi-germania'),
            article('Blănaru, sportiv al Clubului Tadashi, câștigă aur în Germania',
                    'blanaru-sportiv-clubului-tadashi-aur-germania'))

    def test_water_outage_rephrased(self):
        self.assert_grouped(
            article('Apă oprită în Săcele marți', 'apa-oprita-sacele-marti'),
            article('Mai multe străzi din Săcele rămân fără apă marți',
                    'strazi-sacele-raman-fara-apa-marti'))

    def test_same_url_tracking_parameters(self):
        a = article('Un titlu pentru articol', 'un-articol?utm_source=test')
        b = article('Titlu modificat pentru actualizare', 'un-articol?fbclid=test')
        self.assertEqual(len(deduplicate([a, b])), 1)

    def test_distinct_events_are_retained(self):
        pairs = [
            ('Accident grav, trafic blocat pe DN 1 la Predeal',
             'Accident grav, trafic blocat pe DN 11 la Prejmer'),
            ('Corona Brașov câștigă meciul de volei cu Rapid București',
             'Corona Brașov câștigă meciul de volei cu Steaua București'),
            ('Corona Brașov câștigă meciul de volei la București',
             'Corona Brașov câștigă meciul de hochei la București'),
            ('Apa oprită în Săcele marți pe mai multe străzi',
             'Apa oprită în Săcele miercuri pe mai multe străzi'),
            ('Modernizare la Spitalul Județean: investiție în clădirea principală',
             'Incendiu la Spitalul Județean: pompieri la clădirea principală'),
            ('Irineu Darău anunță candidatura la Consiliul Județean Brașov',
             'Irineu Darău cere o dezbatere la Consiliul Județean Brașov'),
            ('Doi câini abandonați peste gardul adăpostului din Brașov',
             'Doi câini adoptați de un liceu din Brașov'),
        ]
        for a, b in pairs:
            with self.subTest(first=a):
                self.assertEqual(len(deduplicate([article(a, 'first'), article(b, 'second')])), 2)

    def test_similar_event_on_different_dates(self):
        a = article('Cod galben de ceață densă la Brașov', 'first')
        b = article(a['title'], 'second', '2026-10-22T12:00:00+03:00')
        self.assertEqual(len(deduplicate([a, b])), 2)

    def test_no_transitive_bridge_across_towns(self):
        items = [article('Apa oprită marți în Săcele pe străzile principale', 'first'),
                 article('Apa oprită marți pe străzile principale', 'second'),
                 article('Apa oprită marți în Codlea pe străzile principale', 'third')]
        self.assertEqual(len(deduplicate(items)), 2)

    def test_full_report_bridges_two_rephrased_titles(self):
        first = article('Biblioteca municipală: laborator digital pentru elevi', 'first', '2026-10-26T14:00:00+02:00')
        second = article('Biblioteca municipală: laborator de robotică pentru profesori', 'second', '2026-10-26T13:00:00+02:00')
        bridge = article('Biblioteca municipală: laborator digital și robotică pentru elevi și profesori', 'third')
        self.assertEqual(len(deduplicate([first, second])), 2)
        self.assertEqual(len(deduplicate([first, second, bridge])), 1)

    def test_idempotent_and_coverage_preserved(self):
        a = article('Biblioteca municipală inaugurează laboratorul digital', 'first')
        b = article(a['title'], 'second')
        once = deduplicate([a, b])
        self.assertEqual(deduplicate(once), once)

    def test_latest_representative_preserves_other_sources(self):
        a = article('Biblioteca municipală inaugurează laboratorul digital', 'first')
        b = article(a['title'], 'second', '2026-10-26T13:00:00+02:00')
        result = deduplicate([a, b])
        self.assertEqual(result[0]['url'], b['url'])
        self.assertEqual(len(result[0]['coverage']), 2)

    def test_full_page_headline_is_preferred(self):
        page = '<meta content="Titlul complet al articolului despre câini" property="og:title">'
        self.assertEqual(extract_headline(page, 'Titlu tăiat...'),
                         'Titlul complet al articolului despre câini')
        page = '<h1>Titlul complet <span>al articolului despre câini</span></h1>'
        self.assertEqual(extract_headline(page, 'Titlu tăiat...'),
                         'Titlul complet al articolului despre câini')
        self.assertEqual(extract_headline('<h1></h1>', 'Titlu de rezervă'), 'Titlu de rezervă')
        self.assertEqual(clean_headline('Titlul complet al articolului - Monitorul Expres - Stiri Brasov', 'Monitorul Expres'),
                         'Titlul complet al articolului')

    def test_empty_or_invalid_url(self):
        self.assertEqual(deduplicate([]), [])
        self.assertEqual(len(deduplicate([{'title': 'Titlu fără URL'}])), 1)

    def test_descriptions_confirm_rephrased_headlines(self):
        a = article('Atac asupra soției: femeia a fugit din apartament', 'first')
        b = article('Și-a atacat soția cu un cuțit', 'second')
        a['summary'] = 'Incident pe Bulevardul Saturn. Copilul a fugit la cofetărie după atacul din apartament. Poliția investighează.'
        b['summary'] = 'Poliția investighează atacul din apartament, pe Bulevardul Saturn. Copilul a fugit la cofetărie.'
        self.assert_grouped(a, b)

    def test_shared_site_description_does_not_merge_unrelated_titles(self):
        a = article('Concert de jazz la Filarmonica Brașov', 'first')
        b = article('Investiții la aeroportul din Brașov', 'second')
        a['summary'] = b['summary'] = 'Cele mai noi știri locale din Brașov. Citește toate informațiile de actualitate.'
        self.assertEqual(len(deduplicate([a, b])), 2)

    def test_collector_writes_grouped_feed_for_both_views(self):
        import update_news
        a = article('Biblioteca municipală inaugurează laboratorul digital', 'first')
        b = article(a['title'], 'second')
        previous_cwd = Path.cwd()
        with tempfile.TemporaryDirectory() as temp:
            try:
                os.chdir(temp)
                Path('sources.json').write_text(json.dumps({'sources': [{'name': 'Test'}]}))
                with patch.object(update_news, 'collect_links', return_value=[a, b]), \
                     patch.object(update_news, 'check_article', side_effect=lambda x: x):
                    update_news.main()
                result = json.loads(Path('news.json').read_text())
            finally:
                os.chdir(previous_cwd)
        self.assertEqual(result['dedupe_version'], 3)
        self.assertEqual(result['count'], 1)
        self.assertEqual(result['raw_count'], 2)
        self.assertEqual(len(result['items'][0]['coverage']), 2)

    def test_informative_description_beats_title_repeated_as_og_description(self):
        title = 'Incendiu în Bran: o femeie a ajuns la spital'
        detail = 'Un incendiu a afectat o casă în Bran, pe strada General Moșoiu. Intervin echipajele SMURD.'
        page = f'<meta property="og:title" content="{title}"><meta property="og:description" content="{title}"><meta name="description" content="{detail}">'
        self.assertEqual(extract_metadata(page, title)[1], detail)

    def test_site_wide_description_cannot_replace_article_description(self):
        title = 'Laboratorul digital pentru elevi a fost inaugurat'
        detail = 'Laboratorul digital pentru elevi este dotat cu echipamente noi.'
        site = 'Suntem un ziar care vă ține la curent cu evenimente culturale, economice, mondene și tot ce trebuie să știți. Răsfoiți articolele noastre.'
        page = f'<meta property="og:title" content="{title}"><meta property="og:description" content="{detail}"><meta name="description" content="{site}">'
        self.assertEqual(extract_metadata(page, title)[1], detail)

    def test_real_duplicate_headlines_use_body_evidence(self):
        cases = json.loads(Path(__file__).with_name('story_regressions.json').read_text())
        for a, b in cases['same_story']:
            with self.subTest(title=a['title']):
                self.assert_grouped(a, b)
                noise = [article('Alte știri despre Bran, biciclete și incendii', f'noise-{i}') for i in range(100)]
                self.assertTrue(StoryMatcher([a, b, *noise]).same(a, b))

    def test_real_unrelated_articles_with_shared_publisher_are_separate(self):
        cases = json.loads(Path(__file__).with_name('story_regressions.json').read_text())
        for a, b in cases['different_stories']:
            with self.subTest(title=a['title']):
                self.assertEqual(len(deduplicate([a, b])), 2)

    def test_body_evidence_ignores_ads_navigation_and_related_articles(self):
        page = '''<nav><p>Navigație cu accident pe autostradă și vremea de mâine.</p></nav>
          <article><header><p>Informații despre redacție și autorul acestui articol.</p></header>
          <div class="entry-content"><p>Incendiul de la locuința de pe strada General Moșoiu a provocat arsuri unei femei.</p>
          <div class="advertisement"><p>Ofertă specială pentru consultații medicale la clinica Test.</p></div>
          <p>Echipajele SMURD au intervenit cu trei autospeciale pentru stingerea incendiului.</p>
          <div class="related-posts"><p>Un alt incendiu a avut loc într-o altă localitate, cu alte victime.</p></div>
          </div></article><footer><p>Informații despre abonamente și politica editorială a publicației.</p></footer>'''
        terms, streets = extract_content_evidence(page)
        self.assertIn('smurd', terms)
        self.assertEqual(streets, ['general mosoiu'])
        for excluded in ('autostrada', 'redactie', 'clinica', 'victime', 'abonamente'):
            self.assertNotIn(excluded, terms)

    def test_pair_decision_is_independent_of_other_news_in_feed(self):
        a = article('Apă oprită în Săcele marți', 'apa-oprita-sacele-marti')
        b = article('Străzile din Săcele rămân fără apă marți', 'strazi-sacele-fara-apa-marti')
        noise = [article('Apă în Săcele și Bran, alte evenimente marți', f'noise-{i}') for i in range(100)]
        self.assertEqual(StoryMatcher([a, b]).same(a, b), StoryMatcher([a, b, *noise]).same(a, b))

    def test_two_fires_at_different_streets_are_not_merged(self):
        a = article('Incendiu la o casă din Bran. O femeie a suferit arsuri', 'first')
        b = article(a['title'], 'second')
        a['streets'], b['streets'] = ['general mosoiu'], ['valeriu bologa']
        a['content_terms'] = b['content_terms'] = sorted(tokens('Pompierii intervin cu trei autospeciale la casa cuprinsă de flăcări, unde o femeie a suferit arsuri la mâini.'))
        self.assertEqual(len(deduplicate([a, b])), 2)


if __name__ == '__main__':
    unittest.main()

