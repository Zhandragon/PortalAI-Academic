# Profile photo retrieval — Windows r62

The structured web reader discarded image links from HTML. Its cached document
contained only flattened text, so subsequent discover(document) also lost images
and table structure. This could send Nice back to broad searches after it had
already identified a useful profile. Extensionless image URLs were saved as .data.

read now returns ranked images/image_urls with source association and placeholder
hints. Up to two million characters of raw HTML are cached across the web worker,
at most one million per page, for discover/data without another request. Eviction
is explicit; text remains readable and callers may use the observed page URL.
Raw HTML never enters the model response. Compacted evidence keeps exact photo URLs.

Profile markup, lazy/srcset images, JSON-LD Person images and matching Scholar
profile IDs are recognized. Other profile IDs, default avatars and decorative
images are marked accordingly. Association is evidence from the page/URL, never
face recognition or verified pictured identity. No owner identity is hard-coded.

download(url,purpose=person_photo) rejects likely placeholder avatars before saving.
Image signatures choose the file extension, including extensionless JPEG URLs.
GitHub avatars can receive a bounded geometry check using existing portable Pillow:
small symmetric few-color patterns are flagged as likely identicons. If Pillow is
absent or analysis is ambiguous, the result stays unknown; it is not proof of a photo.
The direct CLI image route has the same assessment, and automatic image lookup
rejects placeholders unless an avatar/logo/icon is explicitly being sought.

The loaded web workflow asks Nice to inspect an identified profile first, follow
relevant observed profile links, and check the actual image candidate before more
searches. Structured web calls now share the existing image-search progress limits:
8 searches, 6 inspections/downloads and 180 seconds. Other requested tools remain
available. URL checks, TLS verification, bot-challenge handling, account epochs,
publication cleanup and storage reserves remain enforced. Failed downloads are not
automatically replayed.

Source: Agent/web_capabilities.py, web_research.py, web_tools.py,
web_image_quality.py; ControlCenter/image_lookup_policy.py, chat_tool_menu.py,
web_tool_api.py, chat_evidence.py and web_research_evidence.py.
Tests: Maintenance/Tests/test_profile_images.py plus web, account, context and
existing image-lookup regressions. Release validation records executed checks.

This adds no dependencies, models or persistent services. Pixel checking is limited
to GitHub avatars up to one megapixel, sampled at 32x32; it does not load a vision
model. Both SSD installations remain independent and retain the 80 GiB free floor.
Windows is r62; Linux/macOS installer packages remain r51. A normal restart loads
the update. Live model-generated answers and unseen websites remain variable;
retrieval tests do not establish that every Qwen response will choose correctly.
