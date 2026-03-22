---
layout: page
title: Journal
permalink: /journal/
---

{% assign entries = site.journal | sort: "date" | reverse %}

{% for entry in entries %}
- [{{ entry.date | date: "%Y-%m-%d" }}{% if entry.time %} {{ entry.time }}{% endif %}{% if entry.title %} — {{ entry.title }}{% elsif entry.session %} — {{ entry.session }}{% endif %}]({{ entry.url | prepend: site.baseurl }})
{% endfor %}
