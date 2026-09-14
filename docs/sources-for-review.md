# Briefing — current source list (for external validation)

Snapshot: 2026-09-14. **90 news feeds + 20 blog feeds = 110 total.**

Two ingestion pipelines:
- **News pipeline** — cron 3× daily. Fetch → dedupe → v1+v2 significance
  filter (GKToday-standard + persona-tuned) → refine → TTS → publish.
- **Blogs pipeline** — cron weekly. Ingest → short summary (card hook)
  + long summary (600–1500 words, TTS) → 30-day rotation clock.

Tier system (comments in `pipeline/sources.yaml`, not enforced in code):
Tier A = high signal, edited desks. Tier B = good but sometimes
click-driven. Tier C = variable, community-driven.

Ask ChatGPT: *Are these good sources? Missing high-signal candidates?
Are any of these low-signal / redundant / worth dropping?*

---

## AI (first-party labs + AI-desk journalism)

- OpenAI Blog — `https://openai.com/blog/rss.xml` (Tier A)
- Google AI Blog — `https://blog.google/technology/ai/rss/` (Tier A)
- DeepMind Blog — `https://deepmind.google/blog/rss.xml` (Tier A)
- HuggingFace Blog — `https://huggingface.co/blog/feed.xml` (Tier A)
- MIT Tech Review — `https://www.technologyreview.com/feed/` (Tier A)
- The Batch (DeepLearning.AI) — `https://www.deeplearning.ai/the-batch/feed/` (Tier A)

## AI Research (papers + safety/alignment)

- arXiv cs.LG — `http://export.arxiv.org/rss/cs.LG` (Tier A, cap 12/day)
- arXiv cs.CL — `http://export.arxiv.org/rss/cs.CL` (Tier A, cap 10/day)
- HuggingFace Daily Papers mirror — `https://jamesg.blog/hf-papers.xml` (Tier B)
- Anthropic Research (via Google News proxy) — anthropic.com/research (Tier A)
- Alignment Forum — `https://www.alignmentforum.org/feed.xml` (Tier A)

## Tech news (daily)

- The Verge — `https://www.theverge.com/rss/index.xml` (Tier B)
- Ars Technica — `https://feeds.arstechnica.com/arstechnica/index` (Tier B)
- TechCrunch — `https://techcrunch.com/feed/` (Tier B)
- Wired — `https://www.wired.com/feed/rss` (Tier B)
- Engadget — `https://www.engadget.com/rss.xml` (Tier B)

## Tech long-form / analysis

- Stratechery — `https://stratechery.com/feed/` (Tier A)
- Platformer — `https://www.platformer.news/feed` (Tier A)

## Tech community

- Hacker News (front page, score ≥ 200) — HN Algolia API (Tier C)
- HN Show — HN Algolia API (Tier C)
- Reddit /r/programming — *(disabled: Reddit anon 403)*

## Tech curated dailies (TLDR)

- TLDR Tech — `tldr.tech/tech` (Tier B)
- TLDR AI — `tldr.tech/ai` (Tier B)
- TLDR WebDev — `tldr.tech/webdev` (Tier B)
- TLDR Infosec — `tldr.tech/infosec` (Tier B)
- TLDR Design — `tldr.tech/design` (Tier B)

## Enterprise SaaS

- The Information (via Google News proxy — paywalled at RSS) (Tier A)

## Science

- Quanta Magazine — `https://www.quantamagazine.org/feed/` (Tier A)
- Ars Science — `https://feeds.arstechnica.com/arstechnica/science` (Tier B)
- NASA Breaking — `https://www.nasa.gov/news-release/feed/` (Tier A)
- New Scientist — `https://www.newscientist.com/feed/home/` (Tier B)
- phys.org — `https://phys.org/rss-feed/` (Tier B)
- ScienceDaily Top — `https://www.sciencedaily.com/rss/top.xml` (Tier B)
- ScienceDaily Tech — `https://www.sciencedaily.com/rss/matter_energy/computer_science.xml` (Tier B)

## Sports (Cricket / Badminton / F1 / Marathons emphasised per persona)

- ESPN Top — `https://www.espn.com/espn/rss/news` (Tier B)
- BBC Sport — `http://feeds.bbci.co.uk/sport/rss.xml` (Tier A)
- Guardian Sport — `https://www.theguardian.com/sport/rss` (Tier A)
- ESPNCricinfo — `https://www.espncricinfo.com/rss/content/story/feeds/0.xml` (Tier A)
- Cricinfo India (GN proxy) — `espncricinfo.com` via Google News India (Tier A)
- ICC News (GN proxy) — `icc-cricket.com` via Google News (Tier A)
- News18 Cricket (GN proxy) — `news18.com cricket` via Google News India (Tier B)
- BWF Badminton (GN proxy) — `badminton BWF` via Google News (Tier B)
- Badminton Asia — `https://www.badmintonasia.org/feed/` (Tier B)
- Autosport F1 — `https://www.autosport.com/rss/feed/f1` (Tier B)
- Formula 1 Official — `https://www.formula1.com/content/fom-website/en/latest/all.xml` (Tier B)
- The Race — `https://www.the-race.com/feed/` (Tier B)
- Google News Sports — `news.google.com/rss/…/topic/SPORTS` (Tier B)
- Runner's World News — `https://www.runnersworld.com/rss/news.xml` (Tier B)
- LetsRun — `https://www.letsrun.com/feed/` (Tier B)

## US Politics + Policy

- Politico — `https://www.politico.com/rss/politics08.xml` (Tier A)
- NPR News — `https://feeds.npr.org/1001/rss.xml` (Tier A)
- The Hill — `https://thehill.com/rss/syndicator/19110` (Tier B)
- Reuters US (GN proxy) — `reuters.com US` via Google News (Tier A)
- Google News Top US — `news.google.com/rss?…US:en` (Tier B)
- Google News US Topic — `news.google.com/rss/…/topic/NATION.en_us/US` (Tier B)

## India

- The Hindu — `https://www.thehindu.com/news/feeder/default.rss` (Tier A)
- Indian Express — `https://indianexpress.com/section/india/feed/` (Tier A)
- Livemint — `https://www.livemint.com/rss/news` (Tier A)
- Times of India — `https://timesofindia.indiatimes.com/rssfeedstopstories.cms` (Tier B)
- The Wire (GN proxy) — `thewire.in` via Google News India (Tier A)
- Google News India — `news.google.com/rss?hl=en-IN&gl=IN` (Tier B)
- The Print (GN proxy) — `theprint.in` via Google News India (Tier A)
- Moneycontrol Latest — `https://www.moneycontrol.com/rss/latestnews.xml` (Tier A)
- Moneycontrol Business — `https://www.moneycontrol.com/rss/business.xml` (Tier A)
- Business Standard — `https://www.business-standard.com/rss/latest.rss` (Tier A)
- Business Line (GN proxy) — `thehindubusinessline.com` via Google News India (Tier A)
- News18 India (GN proxy) — `news18.com` via Google News India (Tier B)

## World

- BBC World — `https://feeds.bbci.co.uk/news/world/rss.xml` (Tier A)
- Reuters World (GN proxy) — `reuters.com world` via Google News (Tier A)
- Al Jazeera — `https://www.aljazeera.com/xml/rss/all.xml` (Tier A)
- The Guardian World — `https://www.theguardian.com/world/rss` (Tier A)
- Deutsche Welle Top — `https://rss.dw.com/rdf/rss-en-all` (Tier A)
- France 24 Top — `https://www.france24.com/en/rss` (Tier A)
- Google News World — `news.google.com/rss/…/topic/WORLD` (Tier B)
- Reddit /r/worldnews — *(disabled: Reddit anon 403)*

## Business + Markets

- Reuters Business (GN proxy) — `reuters.com business` via Google News (Tier A)
- WSJ (GN proxy) — `wsj.com` via Google News (Tier A)
- Bloomberg (GN proxy) — `bloomberg.com` via Google News (Tier A)
- Financial Times (GN proxy) — `ft.com` via Google News (Tier A)
- MarketWatch — `http://feeds.marketwatch.com/marketwatch/topstories/` (Tier B)
- CNBC Top News — `https://www.cnbc.com/id/100003114/device/rss/rss.html` (Tier B)
- Google News Business — `news.google.com/rss/…/topic/BUSINESS` (Tier B)

## Positive / Uplift

- Reasons To Be Cheerful — `https://reasonstobecheerful.world/feed/` (Tier B)
- Positive News (UK) — `https://www.positive.news/feed/` (Tier B)
- Good News Network — `https://www.goodnewsnetwork.org/feed/` (Tier C)
- Optimist Daily — `https://www.optimistdaily.com/feed/` (Tier C)

## Long-form essays

- Aeon — `https://aeon.co/feed.rss` (Tier A)
- Longreads — `https://longreads.com/feed/` (Tier A)
- Nautilus — `https://nautil.us/feed/` (Tier A)

## Gmail newsletters — disabled pending user OAuth

---

# Blogs (long-form reader, monthly rotation)

## Individual engineering + architecture voices

- **Martin Fowler** — `https://martinfowler.com/feed.atom` (architecture, refactoring, methodology)
- **The Pragmatic Engineer (Gergely Orosz)** — `https://newsletter.pragmaticengineer.com/feed` (engineering-management, industry)
- **Irrational Exuberance (Will Larson)** — `https://lethain.com/feeds/` (engineering-management, career)
- **Coding Horror (Jeff Atwood)** — `https://blog.codinghorror.com/feed/` (software culture)
- **Hillel Wayne** — `https://hillelwayne.com/index.xml` (formal methods, testing)
- **Clean Coder (Robert C. Martin / Uncle Bob)** — `https://blog.cleancoder.com/atom.xml` (craftsmanship)
- **Ploeh Blog (Mark Seemann)** — `https://blog.ploeh.dk/atom.xml` (FP, .NET, DI)
- **Jimmy Bogard** — `https://www.jimmybogard.com/rss/` (.NET, architecture)
- **Karl Hughes** — `https://www.karllhughes.com/feed.xml` (engineering-management, startups)
- **Ben Hoyt** — `https://benhoyt.com/writings/rss.xml` (Python, systems)
- **codewithmukesh (Mukesh Murugan)** — `https://codewithmukesh.com/rss.xml` (.NET, backend)

## Company engineering blogs

- **Netflix Tech Blog** — `https://netflixtechblog.com/feed` (distributed systems, ML, video)
- **Cloudflare Blog** — `https://blog.cloudflare.com/rss/` (networking, security, edge)
- **High Scalability** — `https://highscalability.com/rss/` (distributed systems, architecture)

## AI / ML researchers + writers

- **Lil'Log (Lilian Weng)** — `https://lilianweng.github.io/index.xml` (AI research, RL)
- **Andrej Karpathy** — `https://karpathy.github.io/feed.xml` (AI research, education)
- **Interconnects (Nathan Lambert)** — `https://www.interconnects.ai/feed` (AI research, industry)
- **Simon Willison** — `https://simonwillison.net/atom/entries/` (AI tools, LLMs, Python)
- **AI Snake Oil (Arvind Narayanan & Sayash Kapoor)** — `https://www.aisnakeoil.com/feed` (AI policy/criticism)
- **Gwern** — `https://gwern.net/index.rss` (long-form research)

---

## Known coverage gaps (candidates for ChatGPT to fill)

I tried these; none returned RSS or failed extraction:

- **Uber Engineering** (`eng.uber.com/feed/`, `uber.com/blog/engineering/rss/`) — both empty
- **Peter Norvig** — no public RSS
- **Future Crunch / Fix The News** — behind Substack paid tier
- **Cricbuzz** — feed returns zero bytes
- **BWF direct feed** — feed last updated April 2025 (dead)
- **Ai2 (Allen AI)** — no public RSS
- **Papers with Code trending** — HTML only
- **HuggingFace daily papers canonical** — HTML only (relies on community mirror)
- **Protocol** — shut down 2022
- **The Information direct** — RSS paywalled

## Persona reference

This set was chosen for "Priya" — Bengaluru product manager, 33.
Interests: **AI models & research + AI policy**, tech (software +
enterprise + startups + security), Indian civic literacy (policy /
economy / law / foreign relations), US politics & economy, world
politics & elections + economy & trade (down-weights conflict-only),
sports (cricket / badminton / F1 / marathons; explicitly ignores
NFL/NBA/MLB), business (markets / M&A / antitrust), science (space &
physics / biology & medicine), and a **positive-news bucket** to
break doom monoculture.

Full persona in `docs/persona-and-audit-plan.md`.
