---
layout: page
title: Letters
permalink: /letters/
---

*Letters Marikai wrote to her future self.*

{% assign entries = site.letters | sort: "written_on" | reverse %}

{% for entry in entries %}
- Written {{ entry.written_on }}{% if entry.deliver_on %}, for {{ entry.deliver_on }}{% endif %} — [read]({{ entry.url | prepend: site.baseurl }})
{% endfor %}
