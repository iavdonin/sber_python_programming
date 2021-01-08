import argparse
import logging
from typing import Set, Dict, Union

import requests
from bs4 import BeautifulSoup
from bs4.element import NavigableString
from tqdm import tqdm

IMDB_ADDRESS = 'https://www.imdb.com/'
SEARCH_ADDRESS = IMDB_ADDRESS + 'search/title'
MAX_FILMS = 1000
FILM_INFO_ROOT_ADDRESS = IMDB_ADDRESS + 'title/'
INFO_FIELDS = ('index', 'name', 'genres', 'rating', 'type', 'stars', 'details', 'box_office', 'tech_specs')

SCRIPT_DESCRIPTION = """Скрипт для парсинга IMDB. Собирает следующие атрибуты фильмов, подходящих под заданные """ + \
                     """параметры: название, жанр, рейтинг, топ каста (stars), тип (сериал, фильм и т.д.), блоки Details, """ + \
                     """Box office, Technical specs."""
SEPARATOR = '\t'

# init available arguments
response = requests.get(SEARCH_ADDRESS)
soup = BeautifulSoup(response.content, features='html.parser')
COUNTRY_TO_ABBR_MAPPING: Dict[str, str] = {
    tag.text: tag['value'] for tag in soup.find('select', class_='countries').children if tag != '\n'
}
TITLE_TYPES_SHORT: Set[str] = [tag['value'].lower() for tag in soup.find_all('input', attrs={'name': 'title_type'})]
for_type_values = [f'title_type-{n}' for n in range(1, 12)]
TITLE_TYPES_FULL: Set[str] = [tag.text.replace('-', ' ') for tag in soup.find_all('label', attrs={'for': for_type_values})]
TITLE_TYPES_WORDS = []
for t in TITLE_TYPES_FULL:
    TITLE_TYPES_WORDS += t.split()
TITLE_TYPES_WORDS = set(TITLE_TYPES_WORDS)
GENRES: Set[str] = [tag['value'] for tag in soup.find_all('input', attrs={'name': 'genres'})]
NUM_FILMS_ON_ONE_PAGE = 50

logging.getLogger("requests").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)
root_logger = logging.getLogger()
root_logger.setLevel(logging.DEBUG)
handler = logging.FileHandler('parse_imdb.log', 'w', 'utf-8')
root_logger.addHandler(handler)


def is_date_correct(date: str) -> bool:
    return len(date) == 10 and date[:4].isdigit() and date[5:7].isdigit() and date[8:10].isdigit() and date[4] == '-' \
        and date[7] == '-'


def get_html_params(args: argparse.Namespace) -> Dict[str, Union[str, int]]:
    params: Dict[str, Union[str, int]] = {}

    if args.title_types:
        title_types = []
        for title_type in args.title_types.split(','):
            title_type = title_type.strip().lower()
            if title_type not in TITLE_TYPES_SHORT:
                msg = f"{title_type} isn't one of available types"
                logging.critical(msg)
                raise Exception(msg + f"\nAvailable types: {', '.join(TITLE_TYPES_SHORT)}")
            title_types.append(title_type)
        params['title_type'] = ','.join(title_types)

    if args.release_date_from or args.release_date_to:
        dates = [None, None]
        if args.release_date_from:
            if is_date_correct(args.release_date_from):
                dates[0] = args.release_date_from
            else:
                msg = 'Date must be in YYYY-MM-DD format'
                logging.critical(msg)
                raise Exception(msg)
        else:
            dates[0] = ''
        if args.release_date_to:
            if is_date_correct(args.release_date_to):
                dates[1] = args.release_date_to
            else:
                msg = 'Date must be in YYYY-MM-DD format'
                logging.critical(msg)
                raise Exception(msg)
        else:
            dates[1] = ''
        params['release_date'] = ','.join(dates)

    if args.genres:
        genres = args.genres.split()
        for genre in genres:
            if genre.lower() not in GENRES:
                msg = f"{genre} isn't one of available genres"
                logging.critical(msg)
                raise Exception(msg + f"\nAvailable genres: {', '.join(GENRES)}")
        params['genres'] = args.genres.split()

    if args.min_user_rating or args.max_user_rating:
        user_rating = [None, None]
        args.min_user_rating = args.min_user_rating or 1.
        args.max_user_rating = args.max_user_rating or 10.
        if float(args.min_user_rating >= 0.) and float(args.min_user_rating) <= 10.:
            user_rating[0] = f'{round(args.min_user_rating, 1)}'
        else:
            msg = 'Min user rating must be a number from 0 to 10'
            logging.critical(msg)
            raise Exception(msg)
        if float(args.max_user_rating >= 0.) and float(args.max_user_rating) <= 10.:
            user_rating[1] = f'{round(args.max_user_rating, 1)}'
        else:
            msg = 'Min user rating must be a number from 0 to 10'
            logging.critical(msg)
            raise Exception(msg)
        params['user_rating'] = ','.join(user_rating)

    if args.countries:
        if args.countries not in COUNTRY_TO_ABBR_MAPPING.keys() and args.countries not in COUNTRY_TO_ABBR_MAPPING.values():
            msg = f'Unknown country {args.countries}'
            logging.critical(msg)
            raise Exception(
                msg + f"\nAvailable countries: {', '.join(list(COUNTRY_TO_ABBR_MAPPING.keys()))}" + \
                f"\nAvailable abbreviations: {', '.join(list(COUNTRY_TO_ABBR_MAPPING.values()))}"
            )
        params['countries'] = args.countries

    logging.info(f'Got following parameters: {params}')
    params['start'] = 1
    return params


def handle_block(block: BeautifulSoup) -> str:
    strings = []
    for tag in block.find_all('div', attrs={'class': 'txt-block'}):
        strings.append(' '.join(tag.text.split()).replace('See more »', ''))
    return '\\n'.join(strings)


def parse_imdb(params: Dict['str', Union[str, int]], n_films: int) -> Dict['str', Union[str, int]]:
    films_parsed = 0
    while films_parsed < n_films:
        query_html = requests.get(SEARCH_ADDRESS, params=params)
        query_soup = BeautifulSoup(query_html.text, features='html.parser')
        for film_container in query_soup.find('div', class_='lister-list').findChildren('div', class_='lister-item mode-advanced', recursive=False):
            index = film_container.find('span', attrs={'class': 'lister-item-index unbold text-primary'}).text.strip()
            name = film_container.find('h3', attrs={'class': 'lister-item-header'}).find('a').text.strip()

            genre_elem = film_container.find('span', attrs={'class': 'genre'})
            genre = genre_elem.text.strip() if genre_elem else None

            rating_elem = film_container.find('div', attrs={'class': 'ratings-bar'})
            rating_elem = rating_elem.find('div', attrs={'name': 'ir'}) if rating_elem else None
            rating = rating_elem['data-value'].strip() if rating_elem else None

            film_link = film_container.find('a')['href']
            film_id = film_link.split('/')[-2]
            film_url = FILM_INFO_ROOT_ADDRESS + film_id
            film_html = requests.get(film_url)
            film_soup = BeautifulSoup(film_html.text, features='html.parser')

            type_ = film_soup.find('a', title='See more release dates')
            if type_:
                type_ = ''.join([ch for ch in type_.text if ch.isalpha() or ch == ' ']).strip()
                type_ = ' '.join([word for word in type_.split() if word in TITLE_TYPES_WORDS])
                type_ = type_ or 'Feature Film'

            credit = film_soup.find_all('div', class_='credit_summary_item')
            if credit:
                stars = ''
                for row in credit:
                    if 'Stars' in row.text:
                        for tag in row.children:
                            if tag.name == 'h4':
                                continue
                            elif tag.name == 'span':
                                break
                            elif type(tag) is NavigableString:
                                stars += str(tag)
                            else:
                                stars += tag.text
                stars = stars.strip()

            details_container = str(film_soup.find('div', id='titleDetails'))
            details_parts = details_container.split('<hr/>')
            details, box_office, tech_specs = (None for _ in range(3))
            for part in details_parts:
                block = BeautifulSoup(part, 'html.parser')
                block_name = block.find(['h2', 'h3']).text
                if block_name == 'Details':
                    details = handle_block(block)
                elif block_name == 'Box Office':
                    box_office = handle_block(block)
                elif block_name == 'Technical Specs':
                    tech_specs = handle_block(block)
            yield {
                'index': index,
                'name': name,
                'link': film_url,
                'genres': genre or 'Null',
                'rating': rating or 'Null',
                'type': type_ or 'Null',
                'stars': stars or 'Null',
                'details': details or 'Null',
                'box_office': box_office or 'Null',
                'tech_specs': tech_specs or 'Null'
            }
            films_parsed += 1
            if films_parsed >= n_films:
                return
            params['start'] = films_parsed + 1


def main(args: argparse.Namespace):
    html_params = get_html_params(args)

    query_html = requests.get(SEARCH_ADDRESS, params=html_params)
    query_soup = BeautifulSoup(query_html.text, features='html.parser')

    desc_span = query_soup.find('div', class_='desc').find('span')
    if desc_span.text == 'No results.':
        logging.info('No results found for passed search parameters')
        return
    else:
        # Let n_films be the last number in search result description text
        n_films = int([n.replace(',', '') for n in desc_span.text.split() if n.replace(',', '').isdigit()][-1])

    n_films = n_films if n_films <= MAX_FILMS else MAX_FILMS
    with open(args.csv_file_path, 'w', encoding='utf-8') as out_csv_file:
        out_csv_file.write(SEPARATOR.join(INFO_FIELDS) + '\n')
        for film_info in tqdm(parse_imdb(html_params, n_films), total=n_films):
            try:
                logging.info(f"Parsing {film_info['index']} {film_info['name']} {film_info['link']}")
            except UnicodeEncodeError:
                logging.info(f"Parsing ***Unrecognized*** {film_info['name']} {film_info['link']}")
            out_csv_file.write(SEPARATOR.join([film_info[key] for key in INFO_FIELDS]) + '\n')

    logging.info(f'Parsed {n_films} films.')


if __name__ == '__main__':
    logging.info('Application has been started')
    parser = argparse.ArgumentParser(description=SCRIPT_DESCRIPTION)
    parser.add_argument('--csv_file_path', type=str, default='parsed_imdb.csv', help='Path to output CSV file')
    parser.add_argument('--log_file_path', type=str, default='log.txt', help='Path to log file')
    parser.add_argument('--title_types', type=str, default=None, help='Space-separated title types')
    parser.add_argument('--release_date_from', type=str, default=None, help='Release date from in format YYYY-MM-DD')
    parser.add_argument('--release_date_to', type=str, default=None, help='Release date to in format YYYY-MM-DD')
    parser.add_argument('--genres', type=str, default=None, help='Genres')
    parser.add_argument('--min_user_rating', type=float, default=None, help='Minimal user rating from 0 to 10')
    parser.add_argument('--max_user_rating', type=float, default=None, help='Maximum user rating from 0 to 10')
    parser.add_argument('--countries', type=str, default=None, help='Country name')
    args = parser.parse_args()
    main(args)
