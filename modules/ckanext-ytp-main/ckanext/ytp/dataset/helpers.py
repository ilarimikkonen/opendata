from pylons import config
import json
from ckan.common import c, request
from ckan.lib import helpers
from ckan.logic import get_action
from ckan.plugins import toolkit
from ckanext.scheming.helpers import lang
from ckan.lib import i18n

import os
import logging

log = logging.getLogger(__name__)

from pylons.i18n import gettext

def service_database_enabled():
    return config.get('ckanext.ytp.dataset.service_database_enabled', 'true') == 'true'


def get_json_value(value):
    """ Get value as JSON. If value is not in JSON format return the given value """
    try:
        return json.loads(value)
    except:
        return value


def get_tooltip_content_types(lang=None):
    """ Fetches the  """
    content_types_file = os.path.dirname(os.path.realpath(__file__)) + '/content_types.json'

    if not lang:
        try:
            lang = helpers.lang()
        except TypeError:
            lang = "fi"

    with open(content_types_file) as types:
        ct = json.load(types)

    return ct.get(lang)


def sort_datasets_by_state_priority(datasets):
    """ Sorts the given list of datasets so that drafts appear first and deleted ones last. Also secondary sorts by modification date, latest first. """

    sorted_datasets = []
    sorted_datasets.extend(sorted([dataset for dataset in datasets if dataset['state'] == 'draft'],
                                  key=lambda sorting_key: sorting_key['metadata_modified'], reverse=True))
    sorted_datasets.extend(sorted([dataset for dataset in datasets if dataset['state'] not in ['draft', 'deleted']],
                                  key=lambda sorting_key: sorting_key['metadata_modified'], reverse=True))
    sorted_datasets.extend(sorted([dataset for dataset in datasets if dataset['state'] == 'deleted'],
                                  key=lambda sorting_key: sorting_key['metadata_modified'], reverse=True))
    return sorted_datasets


def get_facet_item_count(facet):
    if c.search_facets.get(facet):
        items = c.search_facets.get(facet)['items']
        return len(items)
    return 0


def get_remaining_facet_item_count(facet, limit=10):
    if c.search_facets.get(facet):
        items = c.search_facets.get(facet)['items']
        return len(items) - 1 - limit
    return 0


def sort_facet_items_by_name(items):
    sorted_items = []
    sorted_items.extend(sorted([item for item in items if item['active'] is True], key=lambda item: (-item['count'], item['display_name'])))
    sorted_items.extend(sorted([item for item in items if item['active'] is False], key=lambda item: (-item['count'], item['display_name'])))
    return sorted_items


def sort_facet_items_by_count(items):
    sorted_items = []
    sorted_items.extend(sorted([item for item in items], key=lambda item: (-item['count'], item['display_name'])))
    return sorted_items


def get_sorted_facet_items_dict(facet, limit=50, exclude_active=False):
    if not c.search_facets or \
            not c.search_facets.get(facet) or \
            not c.search_facets.get(facet).get('items'):
        return []
    facets = []
    for facet_item in c.search_facets.get(facet)['items']:
        if not len(facet_item['name'].strip()):
            continue
        if not (facet, facet_item['name']) in request.params.items():
            facets.append(dict(active=False, **facet_item))
        elif not exclude_active:
            facets.append(dict(active=True, **facet_item))
    sorted_items = []
    sorted_items.extend(sorted([item for item in facets if item['active'] is True], key=lambda item: item['display_name'].lower()))
    sorted_items.extend(sorted([item for item in facets if item['active'] is False], key=lambda item: item['display_name'].lower()))

    # Use function default limit instead of c.search_facets_limits
    if limit:
        return sorted_items[:limit]
    else:
        return sorted_items


def calculate_dataset_stars(dataset_id):
    from ckan.logic import get_action, NotFound
    from ckan import model

    if not is_plugin_enabled('qa'):
        return (0, '', '')
    try:
        context = {'model': model, 'session': model.Session, 'ignore_auth': True}
        qa = get_action('qa_package_openness_show')(context, {'id': dataset_id})

    except NotFound:
        return (0, '', '')
    if not qa:
        return (0, '', '')
    if qa['openness_score'] is None:
        return (0, '', '')

    return (qa['openness_score'],
            qa['openness_score_reason'],
            qa['updated'])


def calculate_metadata_stars(dataset_id):
    """
        Calculate the metadata quality.

        The rating is based on 4 criteria:
            - Field completeness (required / optional) 5 + 5 points
            - More than 50 visits 3 points
            - More than 20 Resource downloads 2 points
            - Comment count: 0,5 points per comment. Max 5 points
            - English or Swedish translations for both title and description: 5 points

    """

    from ckan import model

    score = 0.0

    # Required fields, optional fields, and translated fields, that will be scored by completeness
    required_fields = ['collection_type', 'title', 'notes', 'tags', 'license_id', 'organization', 'content_type']
    optional_fields = ['valid_from', 'valid_till', 'extra_information', 'author', 'author_email', 'owner', 'maintainer', 'maintainer_email']
    translation_fields_en = ['title_en', 'notes_en']
    translation_fields_sv = ['title_sv', 'notes_sv']

    context = {'model': model, 'session': model.Session}
    data = get_action('package_show')(context, {'id': dataset_id})

    # Check that all the required fields are present in the dataset
    if all(data.get(field) for field in required_fields if field is not None):
        score += 5

    # how many optional fields have data?
    optional_count = len(list(data.get(field) for field in optional_fields if data.get(field)))

    # max 5 points from filled optional fields
    score += (optional_count * 5.0 / len(optional_fields))

    # visits from GA
    visits = get_visits_for_dataset(dataset_id)
    visit_count = visits.get("count", 0)
    resource_download_count = visits.get("download_count", 0)

    if visit_count > 50:
        score += 2.5

    if resource_download_count > 20:
        score += 2.5

    # amount of comments
    url = '/dataset/%s' % data.get("name")
    cmnt_cnt = int(get_action('comment_count')(context, {'url': url}))
    score += min((cmnt_cnt / 2.0), 5.0)

    # extras?

    # english translations
    if all(data.get(field) for field in translation_fields_en if data.get(field)):
        score += 5.0
    # swedish translations
    elif all(data.get(field) for field in translation_fields_sv if data.get(field)):
        score += 5.0

    return int(round((score / 5.0), 0))


def is_plugin_enabled(plugin_name):
    return plugin_name in config.get('ckan.plugins', '').split()


def get_upload_size():
    size = config.get('ckan.max_resource_size', 10)

    return size


def get_license(license_id):
    context = {}
    licenses = get_action('license_list')(context, {})

    for license_obj in licenses:
        license_obj_id = license_obj.get('id', None)
        print license_obj
        if license_obj_id and license_obj_id == license_id:
            return license_obj

    return None


def get_visits_for_resource(id):
    from ckanext.googleanalytics.model import ResourceStats

    return ResourceStats.get_all_visits(id)


def get_visits_for_dataset(id):

    from ckanext.googleanalytics.model import PackageStats

    return PackageStats.get_all_visits(id)


def get_geonetwork_link(uuid, organization, lang=None):
    link_stem = ""

    if organization == "suomen-ymparistokeskus":
        link_stem = "http://metatieto.ymparisto.fi:8080/geoportal/catalog/search/resource/details.page?uuid={uuid}"
    else:
        if not lang:
            try:
                lang = helpers.lang()
            except TypeError:
                lang = "en"

        link_stem = "http://www.paikkatietohakemisto.fi/geonetwork/srv/{lang}/main.home?uuid={uuid}"

    return link_stem.format(lang=lang, uuid=uuid)


def unquote_url(url):
    from urllib import quote, unquote

    # leading slash may be interpreted as unicode marker, so remove temporarily
    if url[0:1] == '/':
        url = url[1:]

    unquoted = unquote(url)
    if not isinstance(unquoted, unicode):
        unquoted = unquoted.decode('utf8')

    try:
        unquoted.decode('ascii')
    except UnicodeEncodeError:
        # re-quote characters that should not be in a query string
        unquoted = quote(unquote(unquoted).encode('utf8'), '=&?')
    else:
        unquoted = unquoted.encode('ascii')

    return "/" + unquoted

def scheming_field_only_default_required(field, lang):

    if field and field.get('only_default_lang_required') and lang == config.get('ckan.locale_default', 'en'):
        return True

    return False

def add_locale_to_source(kwargs, locale):
    copy = kwargs.copy()
    source = copy.get('data-module-source', None)
    if source:
        copy.update({'data-module-source': source + '_' + locale})
        return copy
    return copy


_LOCALE_ALIASES = {'en_GB': 'en'}

def scheming_language_text_or_empty(text, prefer_lang=None):
    """
    :param text: {lang: text} dict or text string
    :param prefer_lang: choose this language version if available
    Convert "language-text" to users' language by looking up
    language in dict or using gettext if not a dict
    """
    if not text:
        return u''

    if hasattr(text, 'get'):
        try:
            if prefer_lang is None:
                prefer_lang = lang()
        except:
            pass  # lang() call will fail when no user language available
        else:
            if prefer_lang in _LOCALE_ALIASES:
                prefer_lang = _LOCALE_ALIASES[prefer_lang]
            try:
                return text[prefer_lang]
            except KeyError:
                return ''

    t = gettext(text)
    if isinstance(t, str):
        return t.decode('utf-8')
    return t

def get_lang_prefix():
    language = i18n.get_lang()
    if language in _LOCALE_ALIASES:
        language = _LOCALE_ALIASES[language]

    return language

def call_toolkit_function(fn, args, kwargs):
    return getattr(toolkit,fn)(*args, **kwargs)