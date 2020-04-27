from pandas import DataFrame
from pymongo import MongoClient
from pymongo.uri_parser import parse_uri


def _get_db_instance(db):
    """
    Retrieve the pymongo.database.Database instance.

    Parameters
    ----------
    db: str or pymongo.database.Database
        - if str an instance of pymongo.database.Database will be instantiated and returned
        - if pymongo.database.Database the db instance is returned

    Returns
    -------
    pymongo.database.Database
    """
    if isinstance(db, str):
        db_name = parse_uri(db).get('database')
        if db_name is None:
            # TODO: Improve validation message
            raise ValueError("Invalid db: Could not extract database from uri: %s", db)
        db = MongoClient(db)[db_name]
    return db


def _handle_exists_collection(name, exists, db):
    """
    Handles the `if_exists` argument of `to_mongo`.

    Parameters
    ----------
    if_exists: str
        Can be 'fail', 'replace', 'append'
            - fail: A ValueError is raised
            - replace: Collection is deleted before inserting new documents
            - append: Documents are appended to existing collection
    """

    if exists == "fail":
        if db[name].count() > 0:
            raise ValueError(f"Collection '{name}' already exists.")
        return

    if exists == "replace":
        if db[name].count() > 0:
            db[name].drop()
        return

    if exists == "append":
        return

    raise ValueError(f"'{exists}' is not valid for if_exists")


def _split_in_chunks(lst, chunksize):
    """
    Splits a list in chunks based on provided chunk size.

    Parameters
    ----------
    lst: list
        The list to split in chunks

    Returns
    -------
    result: generator
    A generator with the chunks
    """
    for i in range(0, len(lst), chunksize):
        yield lst[i:i + chunksize]


def _validate_chunksize(chunksize):
    """
    Raises the proper exception if chunksize is not valid.

    Parameters
    ----------
    chunksize: int
    The chunksize to validate.
    """
    if not isinstance(chunksize, int):
        raise TypeError("Invalid chunksize: Must be an int")
    if not chunksize > 0:
        raise ValueError("Invalid chunksize: Must be > 0")


def read_mongo(
    collection,
    query,
    db,
    index_col=None,
    extra=None,
    parse_dates=None,
    columns=None,
    chunksize=None
):
    """
    Read MongoDB query into a DataFrame.

    Returns a DataFrame corresponding to the result set of the query.
    Optionally provide an `index_col` parameter to use one of the
    columns as the index, otherwise default integer index will be used.

    Parameters
    ----------
    collection : str
        Mongo collection to select for querying
    query : list
        Must be an aggregate query.
        The input will be passed to pymongo `.aggregate`
    db : pymongo.database.Database or database string URI
        The database to use
    index_col : str or list of str, optional, default: None
        Column(s) to set as index(MultiIndex).
    extra : list, tuple or dict, optional, default: None
        List of parameters to pass to find/aggregate method.
    parse_dates : list or dict, default: None
        - List of column names to parse as dates.
        - Dict of ``{column_name: format string}`` where format string is
          strftime compatible in case of parsing string times, or is one of
          (D, s, ns, ms, us) in case of parsing integer timestamps.
        - Dict of ``{column_name: arg dict}``, where the arg dict corresponds
          to the keyword arguments of :func:`pandas.to_datetime`
    chunksize : int, default None
        If specified, return an iterator where `chunksize` is the number of
        docs to include in each chunk.
    typ: {‘frame’, ‘series’}, default ‘frame’
        The type of object to recover.

    Returns
    -------
    Dataframe
    """
    params = {}
    if chunksize is not None:
        _validate_chunksize(chunksize)

        params['batchSize'] = chunksize
    db = _get_db_instance(db)
    if extra is None:
        extra = {}

    if extra.get('batchSize') is not None:
        if chunksize is not None:
            raise ValueError("Either chunksize or batchSize must be provided, not both")

    return DataFrame.from_records(
        db[collection].aggregate(query, **{**params, **extra}),
        index=index_col)


def to_mongo(
    frame,
    name,
    db,
    if_exists="fail",
    index=True,
    index_label=None,
    chunksize=None,
):
    """
    Write records stored in a DataFrame to a MongoDB collection.

    Parameters
    ----------
    frame : DataFrame, Series
    name : str
        Name of collection.
    db : pymongo.database.Database or database string URI
        The database to write to
    if_exists : {'fail', 'replace', 'append'}, default 'fail'
        - fail: If table exists, do nothing.
        - replace: If table exists, drop it, recreate it, and insert data.
        - append: If table exists, insert data. Create if does not exist.
    index : boolean, default True
        Write DataFrame index as a column.
    index_label : str or sequence, optional
        Column label for index column(s). If None is given (default) and
        `index` is True, then the index names are used.
        A sequence should be given if the DataFrame uses MultiIndex.
    chunksize : int, optional
        Specify the number of rows in each batch to be written at a time.
        By default, all rows will be written at once.
    """
    db = _get_db_instance(db)
    _handle_exists_collection(name, if_exists, db)
    records = frame.to_dict('records')
    if index is True:
        idx = frame.index
        idx_name = idx.name
        idx_data = idx.tolist()
        for i, record in enumerate(records):
            if index_label is None and idx_name is not None:
                record[idx_name] = idx_data[i]
    if chunksize is not None:
        _validate_chunksize(chunksize)
        result_insert_many = []
        for chunk in _split_in_chunks(records, chunksize):
            result_insert_many.append(db[name].insert_many(chunk))
        return result_insert_many
    return db[name].insert_many(records)
