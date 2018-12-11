import os
import requests
from PIL import Image
from copy import copy
import sqlite3
import random
from mysql import connector
from werkzeug.urls import url_parse
from flask import render_template, redirect, url_for, flash, request, session, jsonify
from flask_login import current_user, login_required, login_fresh, login_user, logout_user

from movie import app
from movie.utils import context_base, roles_accepted, imdb_id_to_imdb_link
from movie.database import get_db, sql_translator
from movie.form import LoginForm, RegistrationForm, MovieDetailForm
from movie.models import User
from movie.api import get_movies_with_params, get_max_movie_id
from movie.retrieve_from_imdb import imdb_retrieve_movie_by_id


# -----------------------------------
# Main Views
# -----------------------------------

@app.route('/index', methods=["GET", "POST"])
@app.route('/')
def index():
    content = copy(context_base)
    content['current_page'] = '/index'
    return render_template('base.html', **content)


# -----------------------------------
# Movie List Views
# -----------------------------------

@app.route('/shopping', methods=["POST", "GET"])
@login_required
def shopping():
    # get movies from database
    data, content = get_movies_with_params('M.movieID, M.title, S.salePrice')
    movie = []
    for select_data in data:
        movieID, title, price = select_data
        movie.append({'id': str(movieID), 'title': title, 'price': price})
    content['images'] = movie
    content['current_page'] = '/shopping'
    return render_template('shopping.html', **content)


# TODO split movie list pages into several pages (next, previous page)
# @app.route('/shopping/page=<int:page_id>', methods=['GET'])
# def get_new_item(page_id):
#     movie = []
#     conn, cur = get_db()
#     cur.execute(sql_translator('select movieID, title from movie limit 20'))
#     data = cur.fetchall()
#     conn.close()
#
#     for select_data in data:
#         movieID, title = select_data
#         price = random.randint(3, 20)
#         movie.append({'id': str(movieID), 'title': title, 'price': price})
#
#     return render_template('shopping.html', images=movie, home=True)


@app.route('/list', methods=["POST", "GET"])
@login_required
def list_movie():
    # get movies from database
    data, content = get_movies_with_params('M.movieID, M.imdbID, M.title, M.year, M.rating, S.amount, S.salePrice')

    movie = []
    for select_data in data:
        movieID, imdbID, title, year, rating, stock, price = select_data
        movie.append({'id': movieID, 'imdbid': imdbID, 'title': title, 'year': year,
                      'rating': rating, 'stock': stock, 'price': price})
    content['movies'] = movie
    content['current_page'] = '/list'
    return render_template('list_metadata.html', **content)


# -----------------------------------
# Authentication Views
# -----------------------------------

@app.route('/login', methods=['GET', 'POST'])
def login():
    content = copy(context_base)

    if current_user.is_authenticated:
        return redirect(url_for('index'))

    form = LoginForm()
    if form.validate_on_submit():
        user = User().query_by_username(form.username.data)
        if user is None or not user.check_password(form.password.data):
            flash('Invalid username or password')
            return redirect(url_for('login'))
        else:
            login_user(user, remember=form.remember_me.data)
            session['store_id'] = '1'
            next_page = request.args.get('next')
            if not next_page or url_parse(next_page).netloc != '':
                if current_user.type == "customer":
                    next_page = url_for('shopping')
                else:
                    next_page = '/manage/movies'
            return redirect(next_page)

    content['title'] = 'Sign In'
    content['form'] = form
    return render_template('login.html', **content)


@app.route('/logout')
@login_required
def logout():
    logout_user()
    session.pop('store_id')
    # flash("Logout Successfully!")
    return redirect(url_for('index'))


@app.route('/register', methods=['GET', 'POST'])
def register():
    content = copy(context_base)

    if current_user.is_authenticated:
        return redirect(url_for('index'))

    form = RegistrationForm()
    if form.validate_on_submit():
        User().new_user(form.username.data, form.name.data, form.password.data, 'customer', form.email.data,
                        form.phone_number.data)
        flash('Congratulations, you are now a registered user!')
        return redirect(url_for('login'))

    content['title'] = 'Register'
    content['form'] = form
    return render_template('register.html', **content)


# -----------------------------------
# User Info Views
# -----------------------------------

@app.route("/receipt/<status>")
@roles_accepted('customer')
def receipt(status):
    """Function to display receipt after purchase"""
    content = copy(context_base)
    transaction_id, status = status.split("&")
    content['transaction_id'] = transaction_id
    content['status'] = status
    content['current_page'] = '/receipt'
    return render_template("receipt.html", **content)


@app.route('/update')
@login_required
def update_info():
    content = copy(context_base)
    content['current_page'] = '/update'
    return render_template('user_info_update.html', **content)


@app.route('/show_history')
@roles_accepted('customer')
def show_history():
    content = copy(context_base)
    conn, cur = get_db()

    cur.execute(sql_translator('select customerID from customer where userID=?'), (current_user.id,))
    customer_id = cur.fetchone()[0]

    # get order history in database.transaction_info
    cur.execute(sql_translator('''
    select paypalID, purchaseDate, region, totalPrice, shippingAddress, status
    from transaction_info
    join store on transaction_info.storeID = store.storeID
    where customerID=?
    order by purchaseDate desc
    '''), (customer_id,))
    records = cur.fetchall()

    history = []
    for record in records:
        order = {
            'paypal_id': record[0],
            'date': record[1],
            'store': record[2],
            'total_price': record[3],
            'shipping': record[4],
            'status': record[5],
            'item_list': []}

        cur.execute(sql_translator('''
        select T.movieID, M.title, T.amount, T.unitPrice
        from transaction_detail T
        join movie M on T.movieID = M.movieID
        where paypalID=?
        '''), (record[0],))
        item_list = cur.fetchall()
        for item in item_list:
            order['item_list'].append({
                'movieID': str(item[0]),
                'title': item[1],
                'amount': item[2],
                'price': item[3]})
        history.append(order)

    content['history'] = history
    content['current_page'] = '/show_history'
    return render_template('show_history.html', **content)


# -----------------------------------
# Management Views
# -----------------------------------

@app.route('/manage/customers')
@roles_accepted('senior_manager', 'manager')
def manage_all_customer():
    content = copy(context_base)
    conn, cur = get_db()
    cur.execute(sql_translator('select name, emailAddress, phoneNumber from customer'))
    customers = cur.fetchall()
    conn.close()
    data = []
    for customer in customers:
        data.append({
            'name': customer[0], 'email': customer[1], 'tele_number': customer[2]
        })
    content['customers'] = data
    content['current_page'] = '/manage/customers'
    return render_template('manage_customers.html', **content)


@app.route('/manage/movies', methods=["GET", "POST"])
@roles_accepted('manager', 'senior_manager')
def manage_movies():
    # get movies from database
    data, content = get_movies_with_params('M.movieID, M.imdbID, M.title, S.salePrice, S.cost, S.amount')

    movie = []
    for select_data in data:
        movie_id, imdb_id, title, price, cost, stock = select_data
        movie.append({'id': str(movie_id), 'imdb_id':imdb_id, 'name': title, 'price': price, 'cost': cost, 'inventory': stock})

    content['movies'] = movie
    content['current_page'] = '/manage/movies'
    return render_template('manage_movies.html', **content)


@app.route('/manage/store', methods=['GET'])
@roles_accepted('senior_manager')
def manage_store():
    # TODO
    return render_template('manage_stores.html')


@app.route('/manage/movie/<int:movie_id>', methods=["GET", "POST"])
@roles_accepted('manager', 'senior_manager')
def manage_movie_detail(movie_id):
    form = MovieDetailForm()
    content = copy(context_base)
    conn, cur = get_db()
    # get movie info
    cur.execute(sql_translator('select * from movie where movieID=?'), (movie_id,))
    movie_info = cur.fetchone()

    if movie_info is None:
        flash("Movie Not Found! Return to Shopping Page.")
        return redirect(url_for('shopping'))

    # get genres
    cur.execute(sql_translator('select genre from genres where movieID=?'), (movie_id,))
    genres = cur.fetchall()

    content['movie_info'] = {
        'movie_id': str(movie_info[0]),
        'title': movie_info[1],
        'summary': movie_info[2],
        'year': movie_info[3],
        'certificate': movie_info[4],
        'rating': movie_info[5],
        'imdb_link': imdb_id_to_imdb_link(movie_info[6]),
        'genres': ", ".join(map(lambda x: x[0], genres))
    }

    if form.is_submitted():
        form.summary.data = request.form.get('summary')
        cur.execute(sql_translator('update movie set title=?, summary=?, year=?, contentRating=?, rating=? where movieID=?'), (
            form.title.data, form.summary.data, int(form.year.data), form.content_rating.data, float(form.rating.data), movie_id
        ))
        conn.commit()
        flash("Changes Saved.")

    content['form'] = form
    content['title'] = movie_info[1]
    return render_template('manage_movie_detail.html', **content)


@app.route('/manage/movie/new', methods=["GET", "POST"])
@roles_accepted('manager', 'senior_manager')
def manage_add_movie():
    form = MovieDetailForm()
    content = copy(context_base)
    conn, cur = get_db()

    new_id = str(get_max_movie_id() + 1)
    store_id = int(session['store_id'])

    # check upload file
    if 'img' in request.files:
        img = request.files['img']
        img.save(os.path.join("movie/static/posters", "{}.{}".format(new_id, img.filename.split('.')[-1])))

    # search on IMDB
    if request.form.get('search') == '':
        if form.imdb_id.data == '':
            flash("Please enter IMDB ID")
        else:
            response = imdb_retrieve_movie_by_id(form.imdb_id.data)
            form.title.data, form.summary.data, form.year.data, form.content_rating.data, form.rating.data, form.imdb_id.data, form.genres.data, poster_url = response
            # download poster
            img = requests.get(poster_url, allow_redirects=True)
            img_filename = 'movie/static/posters/{}.{}'.format(new_id, poster_url.split(".")[-1])
            open(img_filename, 'wb').write(img.content)
            # resize img
            im = Image.open(img_filename)
            im = im.resize((600, 900), Image.ANTIALIAS)
            im.save(img_filename, "JPEG")
            flash("Please refresh your browser by 'Shift+F5' after changing the poster.")

    if request.form.get('add') == '' and not form.validate():
        flash("Please fill in required fields.")
    elif form.validate_on_submit():
        # check if movie existed in movie table
        cur.execute(sql_translator('select movieID from movie where imdbID=? or title=?'), (form.imdb_id.data, form.title.data))
        exist_movie_id = cur.fetchall()

        if exist_movie_id != []:
            # Below is the exmaple for error message, if the added movie is in the stock, showing the error like this.
            return jsonify(message="Added movie already in the stock, current movieID is {}".format(";".join(map(lambda x: str(x[0]), exist_movie_id)))), 500
        else:
            form.summary.data = request.form.get('summary')
            try:
                cur.execute(sql_translator(
                    'insert into movie values (?,?,?,?,?,?,?)'), (
                    new_id, form.title.data, form.summary.data, int(form.year.data), form.content_rating.data,
                    float(form.rating.data), form.imdb_id.data))

                cur.execute(sql_translator(
                    'insert into stock values (?,?,?,?,?,?)'), (
                    store_id, new_id, int(form.stock.data), int(form.stock.data), float(form.price.data), float(form.cost.data)))

                for genre in form.genres.data.split(";"):
                    cur.execute(sql_translator('insert into genres values (?,?)'), (new_id, genre))

                conn.commit()
                flash("New Movie Added.")
                return redirect(url_for('manage_movies'))
            except sqlite3.IntegrityError:
                print('IntegrityError')
            except connector.errors.IntegrityError:
                print('IntegrityError')
            except connector.errors.DataError:
                print('DataError')

    content['form'] = form
    content['max_id'] = new_id
    content['title'] = 'Add New Movie'
    return render_template('manage_add_movie.html', **content)


# -----------------------------------
# Info Views
# -----------------------------------

@app.route('/movie/<int:movie_id>')
@login_required
def movie_details(movie_id):
    content = copy(context_base)
    conn, cur = get_db()
    # get movie info
    cur.execute(sql_translator('select * from movie where movieID=?'), (movie_id,))
    movie_info = cur.fetchone()

    if movie_info is None:
        flash("Movie Not Found! Return to Shopping Page.")
        return redirect(url_for('shopping'))

    # get genres
    cur.execute(sql_translator('select genre from genres where movieID=?'), (movie_id,))
    genres = cur.fetchall()

    content['movie_info'] = {
        'movie_id': str(movie_info[0]),
        'title': movie_info[1],
        'summary': movie_info[2],
        'year': movie_info[3],
        'certificate': movie_info[4],
        'rating': movie_info[5],
        'imdb_link': imdb_id_to_imdb_link(movie_info[6]),
        'genres': ", ".join(map(lambda x: x[0], genres))
    }
    content['title'] = movie_info[1]
    return render_template('movie_detail.html', **content)


# @app.route('/stat')
# @roles_accepted('senior_manager')
# def get_stat_data():
#     content = copy(context_base)
#
#     customer_id = request.args.get('customer_id')
#     month_from = request.args.get('month_from')
#     month_to = request.args.get('month_to')
#     genre = request.args.get('movie_type')
#     options = request.args.get('result')
#     product_id = request.args.get('product_id')
#
#     # amount cost profit
#     # select genres
#     # by time
#     #
#     conn, cur = get_db()
#     if customer_id:
#         content['customer'] = True
#         if not genre:
#             if not product_id:
#                 pass
#
#     if options == 'Cost':
#         pass
#     elif options == 'Profit':
#         pass
#     elif options == 'Sales-Number':
#         # get count
#         cur.execute(sql_translator(''')
#         select COUNT(*)
#         from transactions T
#         where T.customerID=? and T.movieID=? and T.purchaseDate>? and T.purchaseDate<?
#         ''', (customer_id, product_id, month_from, month_to))
#         data = cur.fetchone()
#     else:
#         raise ValueError
#
#
#     data = cur.fetchall()
#
#     cur.execute(sql_translator('select storeID, region from store'))
#     store_data = cur.fetchall()
#
#
#     content['genre'] = True
#     content['product'] = True
#     content['compare_store'] = True
#     content['compare_type'] = True
#
#     content['stats'] = [
#         {'customer_id': 1, 'customer_name': 'tom', 'product_id': 1, 'number': 5},
#     ]
#     content['current_page'] = '/stat'
#     return render_template('stat.html', **content)
