"""Generic OpenAI-compatible text translator; independent of any client.

Copyright (C) 2026 TwinText. SPDX-License-Identifier: AGPL-3.0-only
Credentials belong to the process environment, never to job JSON or health.
"""
from __future__ import annotations
import json
import re
import threading
import urllib.error
import urllib.request
from urllib.parse import urlsplit


class TranslationProviderError(RuntimeError):
    pass


class HTTPTranslator:
    def __init__(self, base, model, key='', source='en', target='zh-CN', cancel=None, timeout=120):
        url = urlsplit(base)
        if url.scheme not in ('https', 'http') or not url.hostname or url.username or url.password or url.query or url.fragment:
            raise ValueError('Expected a clean translation API base URL')
        if not model or not isinstance(model, str):
            raise ValueError('Translation model is required')
        self.endpoint = base.rstrip('/') + '/chat/completions'
        self.model, self.key, self.source, self.target = model, key, source, target
        self.cancel, self.timeout = cancel or threading.Event(), timeout

    def __call__(self, text):
        if not isinstance(text, str):
            raise ValueError('The translator accepts text only')
        if self.cancel.is_set():
            raise RuntimeError('Translation cancelled')
        prompt = (f'Translate the following text from {self.source} to {self.target}. '
                  'Return only the translation. Preserve every <bN>, </bN> and formula placeholder verbatim. '
                  'Preserve citations, numbers and paragraph boundaries. Do not add explanations.')
        body = json.dumps(dict(model=self.model, messages=[dict(role='system', content=prompt), dict(role='user', content=text)])).encode()
        headers = {'Content-Type': 'application/json'}
        if self.key:
            headers['Authorization'] = 'Bearer ' + self.key
        for attempt in range(3):
            if self.cancel.is_set():
                raise RuntimeError('Translation cancelled')
            request = urllib.request.Request(self.endpoint, data=body, headers=headers)
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    raw = response.read(4 * 1024 * 1024 + 1)
                if len(raw) > 4 * 1024 * 1024:
                    raise TranslationProviderError('Translation response exceeds the size limit')
                result = json.loads(raw)['choices'][0]['message']['content']
                if not isinstance(result, str) or not result.strip():
                    raise TranslationProviderError('Translation provider returned no text')
                # Missing math tags must never be accepted as a successful PDF.
                expected = re.findall(r'</?b\d+>', text)
                if any(result.count(tag) != text.count(tag) for tag in set(expected)):
                    raise TranslationProviderError('Translation provider changed formula placeholders')
                if self.cancel.is_set():
                    raise RuntimeError('Translation cancelled')
                return result
            except urllib.error.HTTPError as error:
                retry = error.code in (408, 429, 500, 502, 503, 504)
                if not retry or attempt == 2:
                    raise TranslationProviderError(f'Translation provider HTTP {error.code}') from None
            except (urllib.error.URLError, TimeoutError):
                if attempt == 2:
                    raise TranslationProviderError('Translation provider connection failed or timed out') from None
            except (KeyError, IndexError, TypeError, json.JSONDecodeError):
                raise TranslationProviderError('Invalid translation provider response') from None
            if self.cancel.wait(min(8, 2 ** attempt)):
                raise RuntimeError('Translation cancelled')
