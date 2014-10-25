import copy
import json
import re

import jinja2
from jinja2.ext import Extension

from babelapi.data_type import (
    Binary,
    List,
    Struct,
    Union,
)
from babelapi.lang.lang import TargetLanguage

from generator import Generator

class Jinja2Generator(Generator):
    """
    Jinja2 templates will have access to the :class:`babelapi.api.Api` object,
    as well as the following additional filters:

        pjson (pretty json), is_binary, is_list, is_struct, is_union, and
        is_composite.
    """

    # Matches format of Babel doc tags
    _doc_sub_tag_re = re.compile(':(?P<tag>[A-z]*):`(?P<val>.*?)`')

    def __init__(self, api):

        super(Jinja2Generator, self).__init__(api)

        # File extension -> Language
        self.ext_to_language = {}

        # Language -> dict of template filters
        self.language_to_template_filters = {}

        from babelapi.lang.js import JavascriptTargetLanguage
        from babelapi.lang.python import PythonTargetLanguage
        from babelapi.lang.ruby import RubyTargetLanguage
        self.languages = [JavascriptTargetLanguage(),
                          PythonTargetLanguage(),
                          RubyTargetLanguage()]
        for language in self.languages:
            for ext in language.get_supported_extensions():
                self.ext_to_language[ext] = language

        self.env_vars = {'api': api}
        self.template_env = jinja2.Environment(trim_blocks=True,
                                               lstrip_blocks=True,
                                               extensions=[TrimExtension])

        # Default filter: Pretty JSON
        self.template_env.filters['pjson'] = lambda s: json.dumps(s, indent=2)
        self.template_env.filters['is_binary'] = lambda s: isinstance(s, Binary)
        self.template_env.filters['is_list'] = lambda s: isinstance(s, List)
        self.template_env.filters['is_struct'] = lambda s: isinstance(s, Struct)
        self.template_env.filters['is_union'] = lambda s: isinstance(s, Union)
        self.template_env.filters['is_composite'] = lambda s: isinstance(s, Union)
        def formalize(s):
            return ' '.join(word.capitalize() for word in TargetLanguage._split_words(s))
        self.template_env.filters['formal'] = lambda s: formalize(s)

        # Filters for making it easier to render code (as opposed to HTML)

        # Jinja has format(pattern, text), but no way to do the reverse. This
        # allows us to take a string and insert it into a format string. For
        # example, Ruby symbols: {{ variable|inverse_format(':%s') }}
        self.template_env.filters['inverse_format'] = lambda text, pattern: pattern.format(text)

        # Simple wrapper for slicing a string
        # {{ str|string_slice(1,5,2) }} => str[1:5:2]
        self.template_env.filters['string_slice'] = self._string_slice

        # Substitutes generic Babel doc tags with language-specific ones.
        self.template_env.filters['doc_sub'] = self._doc_sub

        # Add language specified filters
        for language in self.languages:
            for filter_name, method in self.get_template_filters(language).items():
                lang_filter_name = language.get_language_short_name() + '_' + filter_name
                self.template_env.filters[lang_filter_name] = method

        for language in self.languages:
            language_filters = copy.copy(self.template_env.filters)
            for filter_name, method in self.get_template_filters(language).items():
                language_filters[filter_name] = method
            self.language_to_template_filters[language] = language_filters

    def render(self, extension, text):
        if extension in self.ext_to_language:
            language = self.ext_to_language[extension]
            backup_filters = self.template_env.filters
            self.template_env.filters = self.language_to_template_filters[language]
            t = self.template_env.from_string(text)
            rendered_contents = t.render(self.env_vars)
            self.template_env.filters = backup_filters
        else:
            # for extensions like html...
            t = self.template_env.from_string(text)
            rendered_contents = t.render(self.env_vars)

        return rendered_contents

    @staticmethod
    def _doc_sub(doc, *args, **kwargs):
        """
        Substitutes tags in Babel docs with their language-specific
        counterpart. A tag has the following format:

        :<tag>:`<value>`

        'op' and 'struct' are the two supported tags, and should be passed in
        as keywords pointing to macros. The macros should take one argument,
        the value to convert to a language-tailored construct.
        """
        for match in Jinja2Generator._doc_sub_tag_re.finditer(doc):
            matched_text = match.group(0)
            tag = match.group('tag')
            val = match.group('val')
            if tag not in kwargs:
                raise Exception('Could not find doc stub converter for tag %r'
                                % tag)
            doc = doc.replace(matched_text, kwargs[tag](val, *args))
        return doc

    @staticmethod
    def _string_slice(str, start=0, end=None, step=1):
        if end is None:
            end = len(str)
        return str[start:end:step]

    @staticmethod
    def get_template_filters(language):
        return {
                'method': lambda s: language.format_method(s),
                'class': lambda s: language.format_class(s),
                'variable': lambda s: language.format_variable(s),
                'string_value': language.format_string_value,
                'type': language.format_type,
                'pprint': language.format_obj,
                'func_call_args': language.format_func_call_args,
                }

class TrimExtension(Extension):
    """
    A no-op tag for Jinja templates for whitespace control.

    This lets us control whitespace to keep template lines short. For example,
    to put many variables onto one line, we can use

    {{ one }}{%- trim -%}
    {{ two }}{%- trim -%}
    {{ three }}...

    instead of

    {{ one }}{{ two }}{{ three }}...
    """

    tags = set(['trim'])

    def parse(self, parser):
        parser.parse_expression()
        return []