from copy import copy
from werkzeug.urls import url_parse
from flask import render_template, redirect, url_for, flash, request, session
from flask_login import current_user, login_required, login_fresh, login_user, logout_user

from movie import app
from movie.utils import context_base, roles_accepted, imdb_id_to_imdb_link
from movie.database import get_db, sql_translator
from movie.form import LoginForm, RegistrationForm, SearchBarForm
from movie.models import User
from movie.api import get_movies_with_params, get_max_movie_id


# -----------------------------------
# Main Views
# -----------------------------------

@app.route('/index', methods=["GET", "POST"])
@app.route('/')
def index():
    content = copy(context_base)
    content['current_page'] = '/index'
    return render_template('base.html', **content)


@app.route('/test', methods=["GET", "POST"])
def test():
    content = copy(context_base)

    form = SearchBarForm()

    if form.submit():
        choice = form.choice.data
        if choice == 'year' and form.year.data:
            flash("{}".format(form.year.data))
        elif choice == 'genres' and form.genres.data != 'None':
            flash("{}".format(form.genres.data))
        elif choice == 'content_rating' and form.content_rating.data != 'None':
            flash("{}".format(form.content_rating.data))

    print('1', form.search_term.data)
    print('2', form.sort_by.data)
    print('3', form.order.data)

    content['form'] = form
    content['current_page'] = '/test'
    return render_template('test.html', **content)


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
    content['max_id'] = get_max_movie_id()
    content['current_page'] = '/manage/movies'
    return render_template('manage_movies.html', **content)


@app.route('/manage/store', methods=['GET'])
@roles_accepted('senior_manager')
def manage_store():
    # TODO
    return render_template('manage_stores.html')


# -----------------------------------
# Info Views
# -----------------------------------

@app.route('/movie--<int:movie_id>')
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
