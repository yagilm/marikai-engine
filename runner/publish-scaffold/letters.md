---
layout: page
title: Letters
permalink: /letters/
---

*Letters __NAME_CAP__ wrote to her future self.*

{% assign entries = site.letters | sort: "written_on" | reverse %}

{% for entry in entries %}
- Written {{ entry.written_on }} — [read]({{ entry.url | prepend: site.baseurl }})
{% endfor %}
