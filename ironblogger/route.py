# Copyright 2014-2015 Ian Denhardt <ian@zenhack.net>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <http://www.gnu.org/licenses/>
import flask
from flask import make_response
from ironblogger.model import db, Blogger, Blog, Post
from ironblogger.app import app
from ironblogger import config
from ironblogger.date import rssdate, duedate
from collections import defaultdict


def render_template(*args, **kwargs):
    kwargs['cfg'] = config.cfg
    return flask.render_template(*args, **kwargs)


@app.route('/')
def show_index():
    return render_template('index.html')


@app.route('/status')
def show_status():
    posts = db.session.query(Post)\
        .filter(Post.blog_id == Blog.id,
                Blog.blogger_id == Blogger.id,
                Post.timestamp >= Blogger.start_date).all()
    rounds = defaultdict(list)
    for post in posts:
        post_view = {
            'title': post.title,
            'page_url'  : post.page_url,
            'author'    : post.blog.blogger.name,
            'blog_title': post.blog.title,
            'blog_url'  : post.blog.page_url,
            'timestamp' : post.timestamp,
            'counts_for': post.counts_for,
            'late?'     : duedate(post.timestamp) != post.counts_for,
        }
        rounds[duedate(post.timestamp)].append(post_view)
        if post_view['counts_for'] is not None and post_view['late?']:
            rounds[post.counts_for].append(post_view)
    return render_template('status.html',
                           rounds=sorted(rounds.iteritems(), reverse=True))


@app.route('/bloggers')
def show_bloggers():
    return render_template('bloggers.html',
                           bloggers=db.session.query(Blogger).all())


@app.route('/all-posts/rss')
def show_all_posts_rss():
    posts = db.session.query(Post).order_by(Post.timestamp.desc())
    resp = make_response(render_template('all-posts-rss.xml', posts=posts), 200)
    resp.headers['Content-Type'] = 'application/rss+xml'
    return resp


@app.route('/all-posts')
def show_all_posts():
    posts = db.session.query(Post).order_by(Post.timestamp.desc())
    return render_template('all-posts.html', posts=posts, rssdate=rssdate)
