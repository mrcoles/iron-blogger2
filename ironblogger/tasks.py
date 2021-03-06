"""This module contains subroutines not used by the webapp itself.

Most of these are periodic jobs like downloading new posts, computing the
scores for the round, etc. It makes sense to run these as a cron job or
similar.

Routines defined here do not assume they're running in an application context.
Those which need one create one themselves.
"""

import yaml
import json
import arrow
import logging
from getpass import getpass
from datetime import datetime
from os import path

import ironblogger
from .app import app, mail
from .model import Blogger, Blog, Post, User, MalformedPostError, db
from flask_mail import Message

from alembic.config import Config
from alembic import command


def init_db():
    db.create_all()
    alembic_cfg = Config(path.join(
        path.dirname(ironblogger.__file__),
        "..",
        "alembic.ini"
    ))
    command.stamp(alembic_cfg, 'head')


def assign_rounds(since=None, until=None):
    """Assign posts to rounds."""
    if until is None:
        until = datetime.utcnow()
    if since is None:
        since = db.session.query(Blogger.start_date)\
                          .order_by(Blogger.start_date).first()
        if since is None:
            # If this is *still* true, there are no bloggers in the database;
            # we're done!
            return
        # Rows are returned as tuples; we want the raw value:
        since = since[0]

    posts = db.session.query(Post)\
        .filter(Post.counts_for == None,
                Post.timestamp >= since,
                Post.timestamp <= until)\
        .order_by(Post.timestamp.asc()).all()

    for post in posts:
        post.assign_round()

    db.session.commit()


def import_bloggers(file):
    """Import the bloggers (and their blogs) read from ``file``.

    ``file`` should be a file like object, which contains a yaml document.
    The document should be of the same formed as the file ``bloggers.yml`` in
    the old iron-blogger implementation, i.e. the contents of the document
    should be a dictionary:

    * whose keys are the usernames/handles of the bloggers
    * whose values are each a dictionary with the keys:
       * ``start``, which should be date of the form ``YYYY-MM-DD``,
          representing the date on which the blogger joined Iron Blogger
       * ``links``, which should be a list of lists of the form
         ``[title, page_url, feed_url]`` where
         * ``title`` is the title of the blog (in many cases, just the name of
           the blogger).
         * ``page_url`` is the url for the human-readable web page of the blog.
         * ``feed_url`` is the url for the rss or atom feed for the blog.

    ``import_bloggers`` will create the database if it does not exist, and
    populate it with the contents of ``file``.
    """
    session = db.session

    yml = yaml.load(file)
    for blogger in yml.items():
        name = blogger[0]

        # We have to be careful when parsing the date (typically in
        # YYYY-MM-DD form). If we just hand it off unmodified, it will be
        # interpreted in UTC, but the file format requires local time.
        # Otherwise, if the file indicates that a start date is on the first
        # day of a round, and the local timezone is west of UTC, they will be
        # entered as having started the previous day, and thus the previous
        # week.
        start_date = arrow.get(blogger[1]['start']).naive
        start_date = arrow.get(start_date, app.config['IB2_TIMEZONE'])
        start_date = start_date.to('UTC').datetime

        model = Blogger(name=name, start_date=start_date)
        for link in blogger[1]['links']:
            model.blogs.append(Blog(title=link[0],
                                    page_url=link[1],
                                    feed_url=link[2],
                                    ))
        session.add(model)
    session.commit()


def export_bloggers(file):
    """Inverse of `import_bloggers`.

    This outputs a file as described in the docstring for `import_bloggers`,
    based on the contents of the database.
    """
    result = {}
    bloggers = db.session.query(Blogger).all()
    for blogger in bloggers:
        result[blogger.name] = {
            'start': blogger.start_date.strftime("%F"),
            'links': [
                [blog.title, blog.page_url, blog.feed_url]
                for blog in blogger.blogs
            ]
        }
    # If we use the yaml library to dump, We'll get !!python/unicode
    # everywhere, which... ew. Fortunately, JSON is a strict subset of yaml,
    # and it covers enough ground for our purposes, so we'll just output that:
    json.dump(result, file)


def send_reminders():
    text = (
        "Greetings!\n"
        "\n"
        "Just a friendly reminder that this week's Iron Blogger deadline is\n"
        "approaching. If you haven't posted this week already, you should\n"
        "probably get on that!\n"
        "\n"
        "Yours truly,\n"
        "\n"
        "Iron Blogger Robot\n"
    )
    recipients = [r[0] for r in db.session.query(Blogger.email).all()]
    mail.send(Message(subject='Reminder: Iron Blogger post due Sunday!',
                      # The whole point of this setting is that it's supposed
                      # to be a *default*, i.e. it should get used if we don't
                      # pass sender at all. It *used to* work as expected, but
                      # at some point it started throwing an exception about
                      # having no default sender.
                      #
                      # I (zenhack) don't know what happened, and frankly can't
                      # be bothered to investigate further for now. Instead we
                      # just pass it in explcitly
                      sender=app.config['MAIL_DEFAULT_SENDER'],
                      bcc=recipients,
                      body=text))


def shell():
    """Launch a python interpreter.

    The CLI does this inside of an app context, so it's a convienent way to
    play with the API. We also create an outbox for mail, so the user can
    inspect it.
    """
    with mail.record_messages() as outbox:
        import code
        code.interact(local=locals())


def sync():
    """Combination of fetch_posts() and assign_rounds().

    Doing these in one transaction is the norm, so having a single
    wrapper function is useful.
    """
    fetch_posts()
    assign_rounds()


def fetch_posts():
    """Download new posts"""
    logging.info('Syncing posts')
    blogs = db.session.query(Blog).all()
    for blog in blogs:
        try:
            blog.fetch_posts()
        except MalformedPostError as e:
            logging.info('%s', e)


def make_admin():
    """Create an admin user.

    Prompts the user via the CLI for a username and password, and creates
    an admin user.
    """
    username = raw_input('Admin username: ')
    while True:
        pw1 = getpass()
        pw2 = getpass('Password (again):')
        if pw1 == pw2:
            break
        print('Passwords did not match, try again.')
    user = User(name=username, is_admin=True)
    user.set_password(pw1)
    db.session.add(user)
    db.session.commit()
