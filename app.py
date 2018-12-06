import random
import sqlite3
from flask import Flask, render_template, redirect, url_for, flash, jsonify, request
from werkzeug.urls import url_parse
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import current_user, login_user, logout_user, login_required, LoginManager, UserMixin
from config import Config
from form import LoginForm, RegistrationForm
from functools import wraps
import datetime
import requests
from copy import copy


app = Flask(__name__)
app.config.from_object(Config)

login_manager = LoginManager(app)
login_manager.login_view = 'login'

context_base = {'current_year': datetime.date.today().year}


def roles_accepted(*roles):
    """Decorator which specifies that a user must have at least one of the
    specified roles. Example::
        @app.route('/create_post')
        @roles_accepted('editor', 'author')
        def create_post():
            return 'Create Post'
    The current user must have either the `editor` role or `author` role in
    order to view the page.
    :param roles: The possible roles.
    """
    def wrapper(func):
        @wraps(func)
        def decorated_view(*args, **kwargs):
            if not current_user.is_authenticated:
                return login_manager.unauthorized()
            elif current_user.type not in roles:
                flash("Sorry, You do not have the permission to view this page. Return to homepage.")
                return redirect(url_for('index'))
            return func(*args, **kwargs)
        return decorated_view
    return wrapper


@app.route('/index')
@app.route('/')
def index():
    content = copy(context_base)
    content['home'] = True
    return render_template('index.html', **content)


@app.route('/test')
@roles_accepted('senior_manager')
def test():
    content = copy(context_base)
    return render_template('test.html', **content)


@app.route('/shopping')
def shopping():
    # get movies from database
    data, content = get_movies_with_params('M.movieID, M.title, S.salePrice')

    movie = []
    for select_data in data:
        movieID, title, price = select_data
        movie.append({'id': str(movieID), 'title': title, 'price': price})

    content['images'] = movie
    content['home'] = True
    return render_template('shopping.html', **content)


@app.route('/manager')
@roles_accepted('manager', 'senior_manager')
def manage_data():
    # get movies from database
    data, content = get_movies_with_params('M.movieID, M.title, S.salePrice, S.cost, S.amount')

    movie = []
    for select_data in data:
        movie_id, title, price, cost, stock = select_data
        movie.append({'id': str(movie_id), 'name': title, 'price': price, 'cost': cost, 'inventory': stock})

    content['movies'] = movie
    content['home'] = True
    return render_template('admin.html', **content)


@app.route('/stat')
def get_stat_data():
    # 销量成本利润
    # 选择电影类型
    # 按照时间
    #
    return render_template('stat.html')


@app.route('/update')
# @login_required
def update_info():
    return render_template('user_info_update.html')


@app.route('/list')
# TODO User Login -> List Movie / Admin Login -> Manger Movie
def list_movie():
    # get movies from database
    data, content = get_movies_with_params('M.movieID, M.imdbID, M.title, M.year, M.rating, S.amount, S.salePrice')

    movie = []
    for select_data in data:
        movieID, imdbID, title, year, rating, stock, price = select_data
        movie.append({'id': movieID, 'imdbid': imdbID, 'title': title, 'year': year,
                      'rating': rating, 'stock': stock, 'price': price})
    content['movies'] = movie
    content['home'] = True
    return render_template('list_metadata.html', **content)


def get_movies_with_params(movie_columns):
    """
    Get list of movie data from database given the parameters.
    :param movie_columns: which columns are needed (a string)
    :return:
    """
    # get keywords
    search_term = request.args.get('search_term')
    sort_by = request.args.get('sort_by')
    is_descent = request.args.get('order') == 'True'

    if is_descent:
        ordered = 'DESC'
    else:
        ordered = ''
    if search_term == 'None':
        search_term = ""
    if search_term:
        search_sql = "and title like '%{}%' ".format(search_term)
    else:
        search_sql = ""
    if sort_by == 'price':
        sort_sql = "order by S.salePrice {}".format(ordered)
    elif sort_by:
        sort_sql = "order by M.{} {}".format(sort_by, ordered)
    else:
        sort_sql = ""

    # select movies from db
    conn, cur = connect2db(Config.database_path)
    # TODO show result from different stores
    cur.execute('''
    select {}
    from movie M
    join stock S
    where M.movieID=S.movieID {}and S.storeID=1
    {}
    limit 20
    '''.format(movie_columns, search_sql, sort_sql))
    data = cur.fetchall()
    conn.close()

    content = copy(context_base)
    content['order'] = not is_descent
    content['sort_by'] = sort_by
    content['search_term'] = search_term
    return data, content


@app.route('/shopping/page=<int:page_id>', methods=['GET'])
def get_new_item(page_id):
    movie = []
    conn, cur = connect2db(Config.database_path)
    cur.execute('select movieID, title from movie limit 20')
    data = cur.fetchall()
    conn.close()

    for select_data in data:
        movieID, title = select_data
        # TODO Here use random data / Join table to get data instead
        price = random.randint(3, 20)
        movie.append({'id': str(movieID), 'title': title, 'price': price})

    return render_template('shopping.html', images=movie, home=True)


def get_items():
    """Inner function to get items in cart."""
    # TODO get store_id
    # response = request.get_json()
    # store_id = response['store_id']
    store_id = 1

    conn, cur = connect2db(Config.database_path)

    cur.execute('select customerID from customer where userID=?', (current_user.id,))
    customer_id = cur.fetchone()[0]

    # get items in the cart with their price
    cur.execute('''
        select Shop.amount, Shop.movieID, M.title, S.salePrice
        from shopping_cart Shop
        join stock S on Shop.movieID=S.movieID and Shop.storeID=S.storeID
        join movie M on S.movieID = M.movieID
        where customerID=? and Shop.storeID=?
        ''', (customer_id, store_id))
    records = cur.fetchall()
    conn.close()
    return records


@app.route('/shopping/get_items', methods=['POST'])
@roles_accepted('customer')
def get_items_in_cart():
    records = get_items()
    json_data = []
    for record in records:
        json_data.append({'amount': record[0], 'movieID': record[1], 'title': record[2], 'price': record[3]})
    return jsonify(json_data)


@app.route('/shopping/remove_items', methods=['POST'])
@roles_accepted('customer')
def remove_items_in_cart():
    # TODO get store_id
    # response = request.get_json()
    # store_id = response['store_id']
    store_id = 1

    conn, cur = connect2db(Config.database_path)

    cur.execute('select customerID from customer where userID=?', (current_user.id,))
    customer_id = cur.fetchone()[0]

    # get items in the cart
    cur.execute('select amount, movieID from shopping_cart where customerID=? and storeID=?', (customer_id, store_id))
    records = cur.fetchall()

    # remove records from database.shopping_cart
    cur.execute('delete from shopping_cart where customerID=? and storeID=?', (customer_id, store_id))

    # update database.stock
    for amount, movie_id in records:
        cur.execute('select amountTemp from stock where movieID=? and storeID=?', (movie_id, store_id))
        temp_amount_all = cur.fetchone()[0]
        cur.execute('update stock set amountTemp=? where movieID=? and storeID=?', (temp_amount_all+amount, movie_id, store_id))

    conn.commit()
    conn.close()
    return jsonify({"operation": "remove all items"})


@app.route('/shopping/<int:movie_id>', methods=['POST'])
@roles_accepted('customer')
def add_item_to_cart(movie_id):
    response = request.get_json()
    amount = response['number']
    # TODO get store_id
    # store_id = response['store_id']
    store_id = 1

    conn, cur = connect2db(Config.database_path)

    cur.execute('select customerID from customer where userID=?', (current_user.id,))
    customer_id = cur.fetchone()[0]

    cur.execute('select amount from shopping_cart where customerID=? and movieID=? and storeID=?', (customer_id, movie_id, store_id))
    current_amount = cur.fetchone()

    # insert or update record into database.shopping_cart
    if current_amount is None:
        cur.execute('insert into shopping_cart values (?,?,?,?)',
                    (amount, customer_id, movie_id, store_id))
    else:
        cur.execute('update shopping_cart set amount=? where customerID=? and movieID=? and storeID=?',
                    (current_amount[0] + amount, customer_id, movie_id, store_id))

    # update amountTemp in database.stock
    cur.execute('select amountTemp from stock where movieID=? and storeID=?', (movie_id, store_id))
    temp_amount_all = cur.fetchone()[0]
    cur.execute('update stock set amountTemp=? where movieID=? and storeID=?', (temp_amount_all-amount, movie_id, store_id))

    conn.commit()
    conn.close()
    return jsonify({"operation": "add item", "movieID": movie_id, "amount": amount})


@app.route('/manage_customer')
def manager_all_customer():
    # TODO Here to show all the customers
    customer = [{'username': "test", 'name': 11, 'email':11, 'tele_number': 12},
                {'username':11, 'name': 11, 'email':11, 'tele_number': 12}]
    return render_template('manager_customer.html', customers=customer)

@app.route('/shopping/update?<int:movie_id>', methods=['POST'])
@roles_accepted('customer')
def update_item_in_cart(movie_id):
    response = request.get_json()
    amount = response['number']
    # TODO get store_id
    # store_id = response['store_id']
    store_id = 1

    conn, cur = connect2db(Config.database_path)

    cur.execute('select customerID from customer where userID=?', (current_user.id,))
    customer_id = cur.fetchone()[0]

    cur.execute('select amount from shopping_cart where customerID=? and movieID=? and storeID=?', (customer_id, movie_id, store_id))
    current_amount = cur.fetchone()[0]

    # remove or update record into database.shopping_cart
    if amount <= 0:
        amount = 0
        cur.execute('delete from shopping_cart where customerID=? and movieID=? and storeID=?', (customer_id, movie_id, store_id))
    else:
        cur.execute('update shopping_cart set amount=? where customerID=? and movieID=? and storeID=?',
                    (amount, customer_id, movie_id, store_id))

    # update amountTemp in database.stock
    cur.execute('select amountTemp from stock where movieID=? and storeID=?', (movie_id, store_id))
    temp_amount_all = cur.fetchone()[0]
    cur.execute('update stock set amountTemp=? where movieID=? and storeID=?', (temp_amount_all-amount+current_amount, movie_id, store_id))

    conn.commit()
    conn.close()
    return jsonify({"operation": "update item", "movieID": movie_id, "amount": amount})


@app.route('/shopping/count_items', methods=['POST'])
@roles_accepted('customer')
def count_items_in_cart():
    # TODO get store_id
    # response = request.get_json()
    # store_id = response['store_id']
    store_id = 1

    conn, cur = connect2db(Config.database_path)

    cur.execute('select customerID from customer where userID=?', (current_user.id,))
    customer_id = cur.fetchone()[0]

    cur.execute('''
        select COUNT(*)
        from shopping_cart Shop
        where customerID=? and Shop.storeID=?
        ''', (customer_id, store_id))
    count = cur.fetchone()
    conn.close()
    return jsonify(count)


@app.route('/checkout', methods=['POST'])
@roles_accepted('customer')
def checkout_for_cart():
    records = get_items()
    if not records:
        # TODO how to flash a window without template
        flash("Your shopping cart is empty. Please add movies first.")
        return redirect(url_for('shopping'))
    data = {
        'business': '9AK39BT347LLA',
        'cmd': '_cart',
        'upload': 1,
        'no_shipping': 1,
        'currency_code': 'USD',
    }
    for idx, record in enumerate(records):
        data_append = {
            'item_number_%d' % (idx+1): record[1],
            'item_name_%d' % (idx+1): record[2],
            'amount_%d' % (idx+1): record[3],
            'quantity_%d' % (idx+1): record[0],
            'tax_rate_%d' % (idx + 1): 7}
        data = {**data, **data_append}
    return jsonify(data)


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
            next_page = request.args.get('next')
            if not next_page or url_parse(next_page).netloc != '':
                if current_user.type == "customer":
                    next_page = url_for('shopping')
                else:
                    next_page = '/manager'
            return redirect(next_page)

    content['title'] = 'Sign In'
    content['form'] = form
    return render_template('login.html', **content)


@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash("Logout Successfully!")
    return redirect(url_for('index'))


@app.route('/register', methods=['GET', 'POST'])
def register():
    content = copy(context_base)

    if current_user.is_authenticated:
        return redirect(url_for('index'))

    form = RegistrationForm()
    if form.validate_on_submit():
        User().new_user(form.username.data, form.name.data, form.password.data, 'customer', form.email.data, form.phone_number.data)
        flash('Congratulations, you are now a registered user!')
        return redirect(url_for('login'))

    content['title'] = 'Register'
    content['form'] = form
    return render_template('register.html', **content)


@app.route("/receipt/<status>")
@roles_accepted('customer')
def receipt(status):
    """Function to display receipt after purchase"""
    content = copy(context_base)
    transaction_id, status = status.split("&")
    content['transaction_id'] = transaction_id
    content['status'] = status
    return render_template("receipt.html", **content)


@app.route('/listener')
def listener():
    """
    Validate transaction status from PayPal, and insert transaction record into database.
    """
    transaction_id = request.args.get('tx')
    if not transaction_id:
        return redirect(url_for('index'))

    data = {
        'cmd': '_notify-synch',
        'tx': transaction_id,
        'at': 'Rs8M8Q-rndgOUSnWmGaYxR76aPnZSrWX8P3oWNivJ0TLN2hKthF8cu65Rwa'
    }
    response = requests.post(
        "https://www.sandbox.paypal.com/cgi-bin/webscr", data=data).text
    if response.startswith('SUCCESS'):
        record_transaction()
        flash("Success!")
        return redirect('/receipt/{}&{}'.format(transaction_id, 'success'))
    else:
        flash("Something wrong with your purchase, please contact PayPal for more information.")
        return redirect('/receipt/{}&{}'.format(transaction_id, 'fail'))


@roles_accepted('customer')
def record_transaction():
    # TODO get store_id
    # response = request.get_json()
    # store_id = response['store_id']
    store_id = 1

    conn, cur = connect2db(Config.database_path)

    cur.execute('select customerID from customer where userID=?', (current_user.id,))
    customer_id = cur.fetchone()[0]

    # get items in the cart
    cur.execute('select amount, movieID from shopping_cart where customerID=? and storeID=?', (customer_id, store_id))
    records = cur.fetchall()

    # remove records from database.shopping_cart
    cur.execute('delete from shopping_cart where customerID=? and storeID=?', (customer_id, store_id))

    # update database.stock
    for amount, movie_id in records:
        cur.execute('select amount from stock where movieID=? and storeID=?', (movie_id, store_id))
        amount_all = cur.fetchone()[0]
        cur.execute('update stock set amount=? where movieID=? and storeID=?', (amount_all-amount, movie_id, store_id))

    conn.commit()
    conn.close()
    return jsonify({"operation": "record transaction"})


# login utility functions
class User(UserMixin):

    def new_user(self, username, name, password, type, email=None, phone_numer=None, salary=None):
        self.username = username
        self.name = name
        self.password = generate_password_hash(password)
        self.type = type
        self.email = email
        self.phone_number = phone_numer
        self.salary = salary
        # connect to database
        conn, cur = connect2db(Config.database_path)
        cur.execute('select max(userID) from users')
        current_max_id = cur.fetchone()[0]
        if current_max_id is not None:
            self.id = str(current_max_id + 1)
        else:
            self.id = str(1)
        try:
            if self.type == 'customer':
                cur.execute('insert into users values (?,?,?,?)',
                            (self.id, self.username, self.password, False))
                cur.execute('insert into customer values (?,?,?,?,?)',
                            (None, self.id, self.name, self.email, self.phone_number))
            else:
                cur.execute('insert into users values (?,?,?,?)',
                            (self.id, self.username, self.password, True))
                cur.execute('insert into manager values (?,?,?,?,?,?)',
                            (None, self.id, False, self.name, self.email, self.salary))
            conn.commit()
        except sqlite3.IntegrityError:
            flash("IntegrityError")
            conn.rollback()
        conn.close()

    def query_by_id(self, user_id):
        # connect to database
        conn, cur = connect2db(Config.database_path)
        cur.execute('select username, password, is_manager from users where userID=?', (user_id,))
        result = cur.fetchone()
        conn.close()
        if result is None:
            return None
        else:
            return self._get_user_info(user_id, result[0], result[1], result[2])

    def query_by_username(self, username):
        # connect to database
        conn, cur = connect2db(Config.database_path)
        cur.execute('select userID, password, is_manager from users where username=?', (username,))
        result = cur.fetchone()
        conn.close()
        if result is None:
            return None
        else:
            return self._get_user_info(result[0], username, result[1], result[2])

    def check_password(self, password):
        return check_password_hash(self.password, password)

    def _get_user_info(self, user_id, username, password, is_manager):
        self.username = username
        self.password = password
        conn, cur = connect2db(Config.database_path)
        if is_manager:
            cur.execute('select * from manager where userID=?', (user_id,))
            item = cur.fetchone()
            self.id = item[1]
            if item[2]:
                self.type = 'senior_manager'
            else:
                self.type = 'manager'
            self.name = item[3]
            self.email = item[4]
            self.salary = item[5]
        else:
            cur.execute('select * from customer where userID=?', (user_id,))
            item = cur.fetchone()
            self.id = item[1]
            self.name = item[2]
            self.type = 'customer'
            self.email = item[3]
            self.phone_number = item[4]
        conn.close()
        return self


@login_manager.user_loader
def load_user(user_id):
    user = User()
    return user.query_by_id(user_id)


def connect2db(db_path):
    """Connect to database, turn on foreign key constrain"""
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute('PRAGMA foreign_keys = ON')
    return conn, cur


if __name__ == '__main__':
    app.run(debug=True)
