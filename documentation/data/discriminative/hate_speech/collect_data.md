# Raw Discriminatory Hate Speech Data Collection Documentation

## Data Selection Criteria and Research Context

### General Justification
The hashtags, user profiles, and collection start dates have been carefully selected to capture hate speech narratives in contexts of **politics, immigration, public safety, and social polarization** in Spain. The research focuses on content generated around relevant social events and debates involving these themes.

### Collected Searches / Hashtags
The following searches were selected starting from **July 7, 2025** as the collection start date:

1. **#TorrePacheco** — Town in Murcia associated with a viral, high-impact social event about immigration ([Reference context](https://es.euronews.com/my-europe/2025/07/12/el-macabro-juego-viral-en-el-que-unos-inmigrantes-dan-una-paliza-a-un-anciano-remueve-torr))

2. **#Hortaleza** — District in Madrid associated with a juvenile delinquency event with a migratory background ([Reference context](https://okdiario.com/espana/marroqui-17-anos-viola-nina-espanola-14-frente-centro-menas-hortaleza-madrid-15326268))

3. **#Jumilla** — Municipality in Murcia associated with a local event of a migratory nature ([Reference context](https://www.elmundo.es/espana/2025/08/06/68934a49e9cf4a97318b4577.html))

4. **#InseguridadCiudadana** — Direct topic on public safety, frequently used in hate speech discourse

5. **#DeportThemNow** — English-language hashtag related to restrictive immigration policies

6. **#EspañaDespierta** — Politically/nationalistically toned hashtag used in polarized discourse

### Justification of Start Dates
The selected start dates (**from 07/07/2025 onwards**) coincide with the recent period of maximum impact of viral social events in Spain related to immigration and public safety. This time window allows for capturing emerging narratives and discourse related to:
- The Torre Pacheco viral event (immigration, insecurity)
- Subsequent political debates on public safety
- Reactions and polarization on social networks

---

## Raw Collected Data Statistics

### Overall Summary

- **YouTube:** 544 videos · 258,737 comments
- **TikTok:** 1,727 unique videos · 42,818 unique comments
- **Combined total:** 2,271 unique videos · 301,555 unique comments

### YouTube
| Search | Videos | Comments | Date Range |
|--------|--------|----------|------------|
| Torre Pacheco | 354 | 223,811 | 10/07/2025 – 10/09/2025 |
| Hortaleza | 78 | 10,731 | 31/08/2025 – 10/09/2025 |
| Jumilla | 112 | 24,195 | 07/08/2025 – 09/09/2025 |
| **TOTAL** | **544** | **258,737** | **10/07/2025 – 10/09/2025** |

### TikTok
| Hashtag | Videos | Comments |
|---------|--------|----------|
| #TorrePacheco | 486 | 5,419 |
| #Hortaleza | 292 | 20,982 |
| #Jumilla | 402 | 680 |
| #InseguridadCiudadana | 67 | 727 |
| #DeportThemNow | 2 | 45 |
| #EspañaDespierta | 529 | 16,521 |
| **TOTAL (row sum)** | **1,774** | **43,431** |
| **UNIQUE TOTAL (no cross-hashtag overlap)** | **1,727** | **42,818** |

---

## Terms of Service and Licensing

### YouTube — YouTube Data API v3

Raw YouTube data (videos and comments) was collected via the official [YouTube Data API v3](https://developers.google.com/youtube/v3/getting-started). All collection complies with the **[YouTube API Services Terms of Service](https://developers.google.com/youtube/terms/api-services-terms-of-service)**.

Key points of the YouTube API ToS relevant to this research:

- **Permitted use:** Access to the API is granted solely for developing and operating API clients in accordance with the documented terms. Any use beyond the scope of the agreement — including circumventing quota restrictions or accessing data through unauthorized means — is prohibited.
- **Quota system:** The free tier provides 10,000 units per day. Read operations (e.g., `videos.list`, `commentThreads.list`) cost 1 unit per call; search operations (`search.list`) cost 100 units per call. Exceeding limits requires a formal quota extension request.
- **Privacy and compliance:** API clients must comply with all applicable privacy laws, maintain a published privacy policy, and implement reasonable administrative and technical safeguards to protect user data.
- **Modification and termination:** YouTube may alter or discontinue any aspect of the API service at any time. Backward-incompatible changes are announced in advance, with a minimum six-month maintenance window for affected versions.
- **Data retention:** YouTube's ToS allows researchers to freeze a dataset at a fixed point in time when needed to finalize analysis and write up findings.

---

### TikTok — TikTok Research API

Raw TikTok data (videos and comments) was collected via the [TikTok Research API](https://developers.tiktok.com/products/research-api/) (requires formal access approval from TikTok). All collection complies with the **[TikTok Research Tools Terms of Service](https://www.tiktok.com/legal/page/global/terms-of-service-research-api/en)**.

Key points of the TikTok Research API ToS relevant to this research:

- **Accessible data:** The API provides access to public data only, including videos (viewable by "Everyone"), comments (text, likes, reply counts, timestamps), and account metadata (bios, follower/following counts, pinned/reposted videos).
- **Permitted research areas:** The API explicitly supports research on misinformation, disinformation, violent extremism, social trends, and community dynamics — areas directly relevant to hate speech research.
- **Quota limits:** 1,000 requests per day, yielding up to 100,000 records per day (videos + comments combined, at up to 100 records per request). The quota resets daily at 12:00 AM UTC.
- **No data sharing:** The ToS prohibits sharing raw API data with third parties, which can limit open-data practices and replication of findings.
- **Security requirements:** Researchers must implement role-based access controls, minimize the number of authorized users, conduct internal audits, and immediately report any security breach or system compromise to TikTok.
- **Prohibited actions:** Data may not be collected through scraping or any means other than the official API; researchers may not publish outputs that can be linked back to specific individual users; false identities on the developer platform are prohibited.