---
layout: page
title: Creatives
permalink: /creatives/
---

{% assign entries = site.creatives | sort: "date" | reverse %}

{% for entry in entries %}
- [{{ entry.title | default: entry.name }}]({{ entry.url | prepend: site.baseurl }}){% if entry.type %} *({{ entry.type }})*{% endif %}
{% endfor %}
