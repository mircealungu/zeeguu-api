from string import punctuation
from urllib.parse import unquote_plus

import flask
from flask import request

from zeeguu_api.api.translator import (
    minimize_context,
    get_next_results,
    contribute_trans,
)
from zeeguu_core.crowd_translations import (
    get_own_past_translation,
)
from zeeguu_core.model import (
    Bookmark,
    Article,
)
from . import api, db_session
from .utils.json_result import json_result
from .utils.route_wrappers import cross_domain, with_session


@api.route("/get_one_translation/<from_lang_code>/<to_lang_code>", methods=["POST"])
@cross_domain
@with_session
def get_one_translation(from_lang_code, to_lang_code):
    """

    To think about:
    - it would also make sense to separate translation from
    logging; or at least, allow for situations where a translation
    is not associated with an url... or?
    - jul 2021 - Bjorn would like to have the possibility of getting
    a translation without an article; can be done; allow for the
    articleID to be empty; what would be the downside of that?
    - hmm. maybe he can simply work with get_multiple_translations

    :return: json array with translations
    """

    word_str = request.form["word"].strip(punctuation)
    url = request.form.get("url")
    title_str = request.form.get("title", "")
    context = request.form.get("context", "")
    article_id = request.form.get("articleID", None)

    if not article_id:
        # the url comes from elsewhere not from the reader, so we find or create the article
        article = Article.find_or_create(db_session, url)
        article_id = article.id

    minimal_context, query = minimize_context(context, from_lang_code, word_str)

    # if we have an own / teacher translation that is our first "best guess"
    # ML: TODO: word translated in the same text / articleID / url should still be considered
    # as an own translation; currently only if the "context" is the same counts;
    # which means that translating afslore in a previous paragraph does not count
    best_guess = get_own_past_translation(
        flask.g.user, word_str, from_lang_code, to_lang_code, context
    )
    if best_guess:
        likelihood = 1
        source = "Own past translation"
    else:

        translations = get_next_results(
            {
                "from_lang_code": from_lang_code,
                "to_lang_code": to_lang_code,
                "url": url,
                "word": word_str,
                "title": title_str,
                "query": query,
                "context": minimal_context,
            },
            number_of_results=1,
        ).translations

        best_guess = translations[0]["translation"]
        likelihood = translations[0].pop("quality")
        source = translations[0].pop("service_name")

    bookmark = Bookmark.find_or_create(
        db_session,
        flask.g.user,
        word_str,
        from_lang_code,
        best_guess,
        to_lang_code,
        minimal_context,
        url,
        title_str,
        article_id,
    )

    print(bookmark)

    return json_result(
        {
            "translation": best_guess,
            "bookmark_id": bookmark.id,
            "source": source,
            "likelihood": likelihood,
        }
    )


@api.route(
    "/get_multiple_translations/<from_lang_code>/<to_lang_code>", methods=["POST"]
)
@cross_domain
@with_session
def get_multiple_translations(from_lang_code, to_lang_code):
    """
    Returns a list of possible translations in :param to_lang_code
    for :param word in :param from_lang_code except a translation
    from :service

    You must also specify the :param context, :param url, and :param title
     of the page where the word was found.

    The context is the sentence.

    :return: json array with translations
    """

    word_str = request.form["word"].strip(punctuation)
    title_str = request.form.get("title", "")
    url = request.form.get("url")
    context = request.form.get("context", "")
    number_of_results = int(request.form.get("numberOfResults", -1))
    translation_to_exclude = request.form.get("translationToExclude", "")
    service_to_exclude = request.form.get("serviceToExclude", "")

    exclude_services = [] if service_to_exclude == "" else [service_to_exclude]
    exclude_results = (
        [] if translation_to_exclude == "" else [translation_to_exclude.lower()]
    )

    minimal_context, query = minimize_context(context, from_lang_code, word_str)

    data = {
        "from_lang_code": from_lang_code,
        "to_lang_code": to_lang_code,
        "url": url,
        "word": word_str,
        "title": title_str,
        "query": query,
        "context": minimal_context,
    }

    translations = get_next_results(
        data,
        exclude_services=exclude_services,
        exclude_results=exclude_results,
        number_of_results=number_of_results,
    ).translations

    # translators talk about quality, but our users expect likelihood.
    # rename the key in the dictionary
    for t in translations:
        t["likelihood"] = t.pop("quality")
        t["source"] = t["service_name"]

    # ML: Note: We used to save the first bookmark here;
    # but that does not make sense; this is used to show all
    # alternatives; why save the first to the DB?
    # But leaving this note here just in case...

    return json_result(dict(translations=translations))


@api.route("/contribute_translation/<from_lang_code>/<to_lang_code>", methods=["POST"])
@cross_domain
@with_session
def contribute_translation(from_lang_code, to_lang_code):
    """

        User contributes a translation they think is appropriate for
         a given :param word in :param from_lang_code in a given :param context

        The :param translation is in :param to_lang_code

        Together with the two words and the textual context, you must submit
         also the :param url, :param title of the page where the original
         word and context occurred.

    :return: in case of success, the bookmark_id and main translation

    """

    # All these POST params are mandatory
    word_str = unquote_plus(request.form["word"])
    translation_str = request.form["translation"]
    url = request.form.get("url", "")
    context_str = request.form.get("context", "")
    title_str = request.form.get("title", "")
    # when a translation is added by hand, the servicename_translation is None
    # thus we set it to MANUAL
    service_name = request.form.get("servicename_translation", "MANUAL")

    article_id = None
    if "articleID" in url:
        article_id = url.split("articleID=")[-1]
        url = Article.query.filter_by(id=article_id).one().url.as_canonical_string()
    elif "articleURL" in url:
        url = url.split("articleURL=")[-1]
    elif "article?id=" in url:
        article_id = url.split("article?id=")[-1]
        url = Article.query.filter_by(id=article_id).one().url.as_canonical_string()
    else:
        # the url comes from elsewhere not from the reader, so we find or create the article
        article = Article.find_or_create(db_session, url)
        article_id = article.id

    # Optional POST param
    selected_from_predefined_choices = request.form.get(
        "selected_from_predefined_choices", ""
    )

    minimal_context, _ = minimize_context(context_str, from_lang_code, word_str)

    bookmark = Bookmark.find_or_create(
        db_session,
        flask.g.user,
        word_str,
        from_lang_code,
        translation_str,
        to_lang_code,
        minimal_context,
        url,
        title_str,
        article_id,
    )
    # Inform apimux about translation selection
    data = {
        "word_str": word_str,
        "translation_str": translation_str,
        "url": url,
        "context_size": len(context_str),
        "service_name": service_name,
    }
    contribute_trans(data)

    return json_result(dict(bookmark_id=bookmark.id))