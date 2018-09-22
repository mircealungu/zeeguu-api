from zeeguu.model import User
from zeeguu_api.emailer.zeeguu_mailer import ZeeguuMailer

cheers_your_server = '\n\rCheers,\n\rYour Zeeguu Server ;)'


def send_new_user_account_email(username, invite_code='', cohort=''):
    ZeeguuMailer.send_mail(
        f'New Account: {username}',
        [
            f'Code: {invite_code} Class: {cohort}',
            cheers_your_server
        ])


def send_notification_article_feedback(feedback, user: User, article_title, article_url):
    cohort_id = user.cohort_id or 0

    content_lines = [
        f'{feedback} https://www.zeeguu.unibe.ch/read/article?articleURL={article_url}',
        f'User Translations: https://www.zeeguu.unibe.ch/teacher/class/{cohort_id}/student/{user.id}/',
        cheers_your_server
    ]

    ZeeguuMailer.send_mail(f'{user.name} - {article_title}', content_lines)
