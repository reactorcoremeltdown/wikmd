import os
import datetime
import time
import git
import re
import logging
import uuid
import pypandoc
import yaml
import knowledge_graph

from flask import Flask, render_template, request, redirect, url_for, send_from_directory
from werkzeug.utils import secure_filename
from random import randint


WIKMD_CONFIG_FILE = "wikmd-config.yaml"

# Default config parameters
WIKMD_HOST_DEFAULT = "0.0.0.0"
WIKMD_PORT_DEFAULT = 5000
WIKMD_LOGGING_DEFAULT = 1
WIKMD_LOGGING_FILE_DEFAULT = "wikmd.log"

WIKI_DIRECTORY_DEFAULT = "wiki"
IMAGES_ROUTE_DEFAULT = "img"

HOMEPAGE_DEFAULT = "homepage.md"
HOMEPAGE_TITLE_DEFAULT = "homepage"


# .yaml config parameters
with open(WIKMD_CONFIG_FILE) as f:
    yaml_config = yaml.safe_load(f)

# Load config parameters from yaml, env vars or default values (the firsts take precedence)
WIKMD_HOST = yaml_config["wikmd_host"] or os.getenv("WIKMD_HOST") or WIKMD_HOST_DEFAULT
WIKMD_PORT = yaml_config["wikmd_port"] or os.getenv("WIKMD_PORT") or WIKMD_PORT_DEFAULT
WIKMD_LOGGING = yaml_config["wikmd_logging"] or os.getenv("WIKMD_LOGGING") or WIKMD_LOGGING_DEFAULT
WIKMD_LOGGING_FILE = yaml_config["wikmd_logging_file"] or os.getenv("WIKMD_LOGGING_FILE") or WIKMD_LOGGING_FILE_DEFAULT

WIKI_DIRECTORY = yaml_config["wiki_directory"] or os.getenv("WIKI_DIRECTORY") or WIKI_DIRECTORY_DEFAULT
IMAGES_ROUTE = yaml_config["images_route"] or os.getenv("IMAGES_ROUTE") or IMAGES_ROUTE_DEFAULT

HOMEPAGE = yaml_config["homepage"] or os.getenv("HOMEPAGE") or HOMEPAGE_DEFAULT
HOMEPAGE_TITLE = yaml_config["homepage_title"] or os.getenv("HOMEPAGE_TITLE") or HOMEPAGE_TITLE_DEFAULT


UPLOAD_FOLDER = WIKI_DIRECTORY + '/' + IMAGES_ROUTE
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

SYSTEM_SETTINGS = {
    "darktheme": False,
    "listsortMTime": False,
}


app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

logger = logging.getLogger('werkzeug')
logger.setLevel(logging.ERROR)


def git_repo_init() -> git.Repo:
    """
    Function that initializes the git repo of the Wiki (if there is one).
    :return: initialized repo
    """
    try:
        repo = git.Repo.init(WIKI_DIRECTORY)

        # Check if the directory is already a .git repo
        if ".git" in os.listdir(WIKI_DIRECTORY):
            repo.git.checkout("master")  # checkout the master branch
            app.logger.info("Detected existing repo.")
        else:
            repo.git.checkout("-b", "master")  # create a new (-b) master branch
            app.logger.info("There doesn't seem to be a repo, a new one has been created.")

        repo.config_writer().set_value("user", "name", "wikmd").release()
        repo.config_writer().set_value("user", "email", "wikmd@no-mail.com").release()

        return repo

    except Exception as e:
        app.logger.error(f"Error during git initialization: {str(e)}")


def git_pull():
    """
    Function that pulls from the wiki repo.
    """
    try:
        # git pull
        repo.git.pull()
        app.logger.info(f"Pulled from the repo")
    except Exception as e:
        app.logger.info(f"Error during git pull: {str(e)}")


def git_commit(page_name="", commit_type=""):
    """
    Function that commits changes to the wiki repo.
    :param commit_type: could be 'Add', 'Edit' or 'Remove'.
    :param page_name: name of the page that has been changed.
    """
    try:
        # git add --all
        repo.git.add("--all")
        date = datetime.datetime.now()
        commit_msg = f"{commit_type} page '{page_name}' on {str(date)}"
        # git commit -m
        repo.git.commit('-m', commit_msg)
        app.logger.info(f"New git commit: {commit_msg}")
    except Exception as e:
        app.logger.info(f"Nothing to commit: {str(e)}")


def git_push():
    """
    Function that pushes changes to the wiki repo.
    """
    try:
        repo.git.push()
        app.logger.info("Pushed to the repo.")
    except Exception as e:
        app.logger.info(f"Error during git push: {str(e)}")


repo = git_repo_init()


@app.route('/list/', methods=['GET'])
def list_full_wiki():
    return list_wiki("")


@app.route('/list/<path:folderpath>/', methods=['GET'])
def list_wiki(folderpath):
    list = []
    for root, subfolder, files in os.walk(os.path.join(WIKI_DIRECTORY, folderpath)):
        if root[-1] == '/':
            root = root[:-1]
        for item in files:
            path = os.path.join(root, item)
            mtime = os.path.getmtime(os.path.join(root, item))
            if os.path.join(WIKI_DIRECTORY, '.git') in str(path):
                # We don't want to search there
                app.logger.debug(f"skipping {path}: is git file")
                continue
            if os.path.join(WIKI_DIRECTORY, IMAGES_ROUTE) in str(path):
                # Nothing interesting there too
                continue

            folder = root[len(WIKI_DIRECTORY + "/"):]
            if folder == "":
                if item == HOMEPAGE:
                    continue
                url = os.path.splitext(
                    root[len(WIKI_DIRECTORY + "/"):] + "/" + item)[0]
            else:
                url = "/" + \
                    os.path.splitext(
                        root[len(WIKI_DIRECTORY + "/"):] + "/" + item)[0]

            info = {'doc': item,
                    'url': url,
                    'folder': folder,
                    'folder_url': folder,
                    'mtime': mtime,
                    }
            list.append(info)

    if SYSTEM_SETTINGS['listsortMTime']:
        list.sort(key=lambda x: x["mtime"], reverse=True)
    else:
        list.sort(key=lambda x: (str(x["url"]).casefold()))

    return render_template('list_files.html', list=list, folder=folderpath, system=SYSTEM_SETTINGS)


@app.route('/<path:file_page>', methods=['POST', 'GET'])
def file_page(file_page):
    if request.method == 'POST':
        return search()
    else:
        html = ""
        mod = ""
        folder = ""
        try:
            filename = os.path.join(WIKI_DIRECTORY, file_page + ".md")
            # latex = pypandoc.convert_file("wiki/" + file_page + ".md", "tex", format="md")
            # html = pypandoc.convert_text(latex,"html5",format='tex', extra_args=["--mathjax"])
            html = pypandoc.convert_file(filename, "html5",
                                         format='md', extra_args=["--mathjax"], filters=['pandoc-xnos'])
            mod = "Last modified: %s" % time.ctime(os.path.getmtime(filename))
            folder = file_page.split("/")
            file_page = folder[-1:][0]
            folder = folder[:-1]
            folder = "/".join(folder)
            app.logger.info(f"showing html page of {file_page}")
        except Exception as a:
            app.logger.info(a)
        return render_template('content.html', title=file_page, folder=folder, info=html, modif=mod,
                               system=SYSTEM_SETTINGS)


@app.route('/', methods=['POST', 'GET'])
def index():
    if request.method == 'POST':
        return search()
    else:
        html = ""
        app.logger.info("homepage displaying")
        try:
            html = pypandoc.convert_file(
                os.path.join(WIKI_DIRECTORY, HOMEPAGE), "html5", format='md', extra_args=["--mathjax"],
                filters=['pandoc-xnos'])

        except Exception as e:
            app.logger.error(e)

        return render_template('index.html', homepage=html, system=SYSTEM_SETTINGS)


@app.route('/add_new', methods=['POST', 'GET'])
def add_new():
    if request.method == 'POST':
        page_name = fetch_page_name()
        save(page_name)
        git_commit(page_name, "Add")

        return redirect(url_for("file_page", file_page=page_name))
    else:
        return render_template('new.html', upload_path=IMAGES_ROUTE, system=SYSTEM_SETTINGS)


@app.route('/edit/homepage', methods=['POST', 'GET'])
def edit_homepage():
    if request.method == 'POST':
        page_name = fetch_page_name()
        save(page_name)
        git_commit(page_name, "Edit")

        return redirect(url_for("file_page", file_page=page_name))
    else:
        with open(os.path.join(WIKI_DIRECTORY, HOMEPAGE), 'r', encoding="utf-8") as f:
            content = f.read()
        return render_template("new.html", content=content, title=HOMEPAGE_TITLE, upload_path=IMAGES_ROUTE,
                               system=SYSTEM_SETTINGS)


@app.route('/remove/<path:page>', methods=['GET'])
def remove(page):
    filename = os.path.join(WIKI_DIRECTORY, page + '.md')
    os.remove(filename)
    git_commit(page_name=page, commit_type="Remove")
    return redirect("/")


@app.route('/edit/<path:page>', methods=['POST', 'GET'])
def edit(page):
    filename = os.path.join(WIKI_DIRECTORY, page + '.md')
    if request.method == 'POST':
        page_name = fetch_page_name()
        if page_name != page:
            os.remove(filename)

        save(page_name)
        git_commit(page_name, "Edit")

        return redirect(url_for("file_page", file_page=page_name))
    else:
        with open(filename, 'r', encoding="utf-8") as f:
            content = f.read()
        return render_template("new.html", content=content, title=page, upload_path=IMAGES_ROUTE,
                               system=SYSTEM_SETTINGS)


def save(page_name):
    """
    Function that saves a *.md page.
    :param page_name: name of the page
    """
    content = request.form['CT']
    app.logger.info(f"Saving {page_name}")

    try:
        filename = os.path.join(WIKI_DIRECTORY, page_name + '.md')
        dirname = os.path.dirname(filename)
        if not os.path.exists(dirname):
            os.makedirs(dirname)
        with open(filename, 'w') as f:
            f.write(content)
    except Exception as e:
        app.logger.error(f"Error while saving {page_name}: {str(e)}")


@app.route('/' + IMAGES_ROUTE, methods=['POST', 'DELETE'])
def upload_file():
    app.logger.info("uploading image...")
    # Upload image when POST
    if request.method == "POST":
        file_names = []
        for key in request.files:
            file = request.files[key]
            filename = secure_filename(file.filename)
            # bug found by cat-0
            while filename in os.listdir(os.path.join(WIKI_DIRECTORY, IMAGES_ROUTE)):
                app.logger.info(
                    "There is a duplicate, solving this by extending the filename...")
                filename, file_extension = os.path.splitext(filename)
                filename = filename + str(randint(1, 9999999)) + file_extension

            file_names.append(filename)
            try:
                app.logger.info(f"Saving {filename}")
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            except Exception as e:
                app.logger.error(f"Error while saving image: {str(e)}")
        return filename

    # DELETE when DELETE
    if request.method == "DELETE":
        # request data is in format "b'nameoffile.png" decode by utf-8
        filename = request.data.decode("utf-8")
        try:
            app.logger.info(f"removing {str(filename)}")
            os.remove((os.path.join(app.config['UPLOAD_FOLDER'], filename)))
        except Exception as e:
            app.logger.error(f"Could not remove {str(filename)}")
        return 'OK'


@app.route('/knowledge-graph', methods=['GET'])
def graph():
    global links
    links = knowledge_graph.find_links()
    return render_template("knowledge-graph.html", links=links, system=SYSTEM_SETTINGS)

# Translate id to page path


@app.route('/nav/<path:id>/', methods=['GET'])
def nav_id_to_page(id):
    for i in links:
        if i["id"] == int(id):
            return redirect("/"+i["path"])
    return redirect("/")


@app.route('/' + IMAGES_ROUTE + '/<path:filename>')
def display_image(filename):
    # print('display_image filename: ' + filename)
    return send_from_directory(UPLOAD_FOLDER, filename, as_attachment=False)


@app.route('/toggle-darktheme/', methods=['GET'])
def toggle_darktheme():
    SYSTEM_SETTINGS['darktheme'] = not SYSTEM_SETTINGS['darktheme']
    return redirect(request.referrer)  # redirect to the same page URL


@app.route('/toggle-sorting/', methods=['GET'])
def toggle_sort():
    SYSTEM_SETTINGS['listsortMTime'] = not SYSTEM_SETTINGS['listsortMTime']
    return redirect("/list")


def search():
    """
    Function that searches for a term and shows the results.
    """
    search_term = request.form['ss']
    escaped_search_term = re.escape(search_term)
    found = []

    app.logger.info(f"searching for {search_term} ...")

    for root, subfolder, files in os.walk(WIKI_DIRECTORY):
        for item in files:
            path = os.path.join(root, item)
            if os.path.join(WIKI_DIRECTORY, '.git') in str(path):
                # We don't want to search there
                app.logger.debug(f"skipping {path} is git file")
                continue
            if os.path.join(WIKI_DIRECTORY, IMAGES_ROUTE) in str(path):
                # Nothing interesting there too
                continue
            with open(root + '/' + item, encoding="utf8") as f:
                fin = f.read()
                try:
                    if (re.search(escaped_search_term, root + '/' + item, re.IGNORECASE) or
                            re.search(escaped_search_term, fin, re.IGNORECASE) != None):
                        # Stripping 'wiki/' part of path before serving as a search result
                        folder = root[len(WIKI_DIRECTORY + "/"):]
                        if folder == "":
                            url = os.path.splitext(
                                root[len(WIKI_DIRECTORY + "/"):] + "/" + item)[0]
                        else:
                            url = "/" + \
                                  os.path.splitext(
                                      root[len(WIKI_DIRECTORY + "/"):] + "/" + item)[0]

                        info = {'doc': item,
                                'url': url,
                                'folder': folder,
                                'folder_url': root[len(WIKI_DIRECTORY + "/"):]}
                        found.append(info)
                        app.logger.info(f"found {search_term} in {item}")
                except Exception as e:
                    app.logger.error(f"There was an error: {str(e)}")

    return render_template('search.html', zoekterm=found, system=SYSTEM_SETTINGS)


def fetch_page_name() -> str:
    page_name = request.form['PN']
    if page_name[-4:] == "{id}":
        page_name = f"{page_name[:-4]}{uuid.uuid4().hex}"
    return page_name


def run_wiki():
    """
    Function that runs the wiki as a Flask app.
    """
    if int(WIKMD_LOGGING) == 1:
        logging.basicConfig(filename=WIKMD_LOGGING_FILE, level=logging.INFO)

    app.run(debug=True, host=WIKMD_HOST, port=WIKMD_PORT)


if __name__ == '__main__':
    run_wiki()


