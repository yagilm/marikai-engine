---
layout: page
title: Essays
permalink: /essays/
---

{% assign entries = site.essays | sort: "date" | reverse %}

{% for entry in entries %}
- {{ entry.date | date: "%Y-%m-%d" }}{% if entry.time %} {{ entry.time }}{% endif %} — [{{ entry.title | default: entry.name }}]({{ entry.url | prepend: site.baseurl }}){% if entry.topic %} — *{{ entry.topic }}*{% endif %}
{% endfor %}
