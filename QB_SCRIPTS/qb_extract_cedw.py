# -- * **************************************************************************
# -- * File Name        : qb_extract_cedw.py
# -- *
# -- * Description      :    
# -- *                   Step 1: Read the Json files to get the database
# -- *                      connection paramaters and the email notification
# -- *                      addresses
# -- *
# -- *                   Step 2: Establish conections to the Automation/Control,
# -- *                      QuickBooks source and CEDW QuickBooks target DB's
# -- *
# -- *                   Step 3: Retrieve a list of the valid tables and their
# -- *                      respctive column names for extract
# -- *
# -- *			 Step 4: For each table prepare and execute a select 
# -- *                      from the source and prepare and execute an insert
# -- *                      into the target table
# -- *
# -- *			 Step 5: Close all the DB Conections		
# -- *
# -- * Purpose          : Extract all the data from the QuickBooks source and
# -- *                      load it into the CEDW target for reporting purposes
# -- * Date Written     : Dec 2019
# -- * Input Parameters : N/A
# -- * Input Files      : EmailNotification.json, ConnectionData.json
# -- * Output Parameters: N/A
# -- * Tables Read      : Third_Party_Source_Etl_Execution and ALL tables contained
# -- *                      in this table (includes the source and target tables)   
# -- * Tables Updated/Inserted   : ALL tables in the
# -- *                              Third_Party_Source_Etl_Execution table
# -- * Run Frequency    : Every 4 hours
# -- * Developed By     : Steve Wilson - ProjectX
# -- * Code Location    : https://github.com/PXLabs/QuickBooksExtract
# -- *   
# -- * Version   	Date   		Modified by     Description
# -- * v1.0	   	Dec 12, 2019	Steve Wilson	Initial Code created
# -- * v2.0	   	Dec 18, 2019	Steve Wilson	Added notification &
# -- *                                                  connection security
# -- * v2.1	   	Dec 19, 2019	Steve Wilson	Cleaned up notification
# -- * v2.2             Jan 7, 2020     Steve Wilson    Added dbUtil
# -- *                                                  functionality
# -- * v2.3             Feb 28, 2020    Steve Wilson    Added ETL Control
# -- *                                                  functionality
# -- * **************************************************************************
# -- * **************************************************************************
# Packages Required
#
# -- * **************************************************************************
# Libraries Required
#
import time
import logging
from datetime import datetime
import json
import smtplib
import dbUtil as db
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import etlControl

""" The overall program will retrieve all the table and column data that
    was created and formated by the process "populate_selection_table" and
    stored in the table "Third_Party_Source_Etl_Execution".
    The process will extract data from the QuickBooks source and insert
    it into a SQL Server reporting database
"""

def getEmailUsers(emailData, notificationType):
    """ Retrieve the email addresses to notify for failure of success """
    email_list = emailData[notificationType]['email_address']
    return email_list #'SuccessEmail'


def notifyEmailUsers(process_execution_ind, email_users, msg_text):
    """
        Opens an email server and sends aeither a success or failure message
        to the passed recipients
        
        :param process_execution_ind: Success 'S' or Failure 'F' indicator
        :param email_users: List of emal user to send a message to
        :param msg_text: Message to send to the email list
        :return: None 
    """
    mail_server = smtplib.SMTP(host='pxltd-ca.mail.protection.outlook.com',
                                   port='25')
    logging.info('Opened Mail Server')
    msg = MIMEMultipart()       # create a message
    msg['From'] = 'sqlalerts@pxltd.ca'
    msg['To'] = ', '.join(email_users)

    if process_execution_ind == 'S':
        msg['Subject'] = 'CEDW QuickBooks extract Successful'
    else:
        msg['Subject'] = 'CEDW QuickBooks extract Failed'
        
    message_body = MIMEText(msg_text, "plain")
    msg.attach(message_body)
    mail_server.send_message(msg)
    
    if process_execution_ind == 'S':
        logging.info('Sent success email to {}'.format(msg['To']))
    else:
        logging.info('Sent Failure email to {}'.format(msg['To']))

    mail_server.quit()
    

def prep_QB_columns(src_column_names):
    """
        For use in the data selection from QB the column statements must
        have a specific format. All doulble quotes are removed and then
        will be added back for the column name Desc
        
        :param src_column_names: The string of column names to be formatted
        :return: A formatted string 
    """
    
    fmt_column_names = src_column_names.replace('"','')
    fmt_column_names = fmt_column_names.replace(',Desc,',',"Desc",')
    if fmt_column_names.count(',Desc') != 0 and \
            fmt_column_names.count(',Description') == 0:
        fmt_column_names = fmt_column_names.replace(',Desc',',"Desc"')
        
    return(fmt_column_names)


def replace_dt_columns(column_data):
    """
        This function will format all datetime data types which are returned
        from the select statement. It modifies the python datetime type to
        a string format accepted by SQL Server

        :param column_data: The string of date time data type to be formatted
        :return: A formatted date string
    """
    new_list = []
    for column in column_data:
        if isinstance(column, datetime):      
            date_str_fmt = '{:%Y-%m-%d %H:%M:%S}'.format(column)
            new_list.append(date_str_fmt)
        elif isinstance(column, bool):
            new_list.append(column)
        else:
            new_list.append(column)
            
    return new_list

def main():
    try:
        process_start_time = time.time()
        fetch_row_size = 3000   # process in batches to manage memory

        #  Setup and configure the Log file
        log_file = 'C:\QB_SCRIPTS\ETL_Logs\ETL_Log' + \
                   datetime.today().strftime('%Y-%m-%d') + '.log'
        logging.basicConfig(filename=log_file, level=logging.INFO, \
                            filemode='a', format='%(asctime)s %(message)s')
        logging.info('*****************************************************' \
                '***************************')
        logging.info('Start of process')
        
        '''Obtain the db login parameters. The file contents will be restricted
            as it contains passwords
        '''
        try:
            with open("C:\QB_SCRIPTS\ConnectionData.json") as f:
                DbConnectionData = json.load(f)
            logging.info('Retrieved connection data')
        except Exception as err:
            logging.info('Error reading connection data error - %s', str(err))
            raise()

        # Obtain the notification recipients from a file.
        try:
            with open("C:\QB_SCRIPTS\EmailNotification.json") as f:
                emailNotification = json.load(f)

            successEmailUsers = getEmailUsers(emailNotification, 'SuccessEmail')
            failureEmailUsers = getEmailUsers(emailNotification, 'FailureEmail')
            logging.info('Retrieved email notification data')
        except:
            logging.info('Error reading Email Notification data %s', str(err))
            raise()


        ''' Create a connection to the QB Target database'''
        ctl_dbConn = db.dbConn(DbConnectionData, 'ControlConnection')
        logging.info('Opened QB Target DB connection')
        
        ''' Create a connection to the QB Source database '''
        QB_src_dbConn = db.dbConn(DbConnectionData, 'QbSourceConnection')
        logging.info('Opened QB Source DB connection')

        ''' Create a connection to the QB Target database'''
        QB_tgt_dbConn = db.dbConn(DbConnectionData, 'QbTargetConnection')
        logging.info('Opened QB Target DB connection')


        ''' Retrieve all the valid tables from the QB ETL execution table '''
        selectStmt = ("SELECT Source_Table_Nm, Source_Column_Names FROM dbo."
                     "[Third_Party_Source_Etl_Execution]"
                     " WHERE Extract_Process_Active_Ind = 'Y' "
                    "AND Source_Db_Nm = 'QB_CEDW';")
        valid_table_rows = ctl_dbConn.selectRows(selectStmt)
        num_of_table_rows = len(valid_table_rows)

        logging.info('Number of Tables to Process -> ()'.format(
            num_of_table_rows))
        #print('Number of Rows-> ', num_of_table_rows)

        ''' Read through the tables to be extracted from '''
        for tables_processed, source_table in enumerate(valid_table_rows):
            extract_start_time = time.time()
            table_name = source_table[0]    
            column_names = source_table[1]
            total_rows_read = 0
            # format the columns
            sq_column_names = prep_QB_columns(source_table[1])
            ETL_step_nm = 'QB_CEDW-' + table_name

            # This is the ETL API Wrapper call before the start of the ETL
            
            init_response = etlControl.etlStartProcess(ETL_step_nm,'','')
            '''
            if init_response['status'] == 'Fail':
                print('Init Process failed ->', init_response['status'])
                logging.info(f'Init Process failed -> '
                             '{init_response["status"]}')
                raise()
            '''
            

            #print('Table name -> ', table_name)
            logging.info('Processing Table -> %s', table_name)

            ''' This table is a special case, it contains a salary column
                which is required to be encrypted. The column 'xx' is added
                to the target table and will contain the raw (unencrypted
                value). It will be set to NULL just after the data is loaded.
                The existing list of columns is modified by adding xx to
                the insert and rate to the Select
            '''
            if table_name == 'EmployeeEarning':
                column_names += ',temp_rate'   # PayrollInfoEarningsRate_ENCRPTD
                sq_column_names += ',PayrollInfoEarningsRate'        
                 
            ''' Select and process the table. Create the Select Statement
                from the extract table '''
            selectStmt = "SELECT {} FROM {}".format(sq_column_names, table_name)


            ''' Before inserting rows remove all the previous rows, truncate
                table'''
            full_table_nm = "{}.{}.[{}]".format(ctl_dbConn.getDbName(),
                                                ctl_dbConn.getDbOwner(),
                                                table_name)
             
            QB_tgt_dbConn.truncateTable(full_table_nm)
            logging.info('Table Truncated -> {}'.format(full_table_nm))

            ''' Build the Insert statement, use the columns in the table,
                determine the number of columns by counting the number of
                commas in the column_names column and adding one more.
                Use these as place holders in the form a "?", then use the
                execute many statement to insert all the rows for all values
                from the list '''
            insertStmt = ("INSERT INTO {}.{}.[{}] ({}) VALUES (".format(
                                                ctl_dbConn.getDbName(),
                                                ctl_dbConn.getDbOwner(),
                                                table_name,
                                                column_names))

            ''' find the number of columns in the names There will be one
                less comma so add another at the end'''
            for i in range(column_names.count(',')):
                insertStmt += '?,'

            insertStmt += '?)'  # Add the final placeholder

            # select returns partial query results to manage large tables
            batch_values = QB_src_dbConn.selectRowsWithCursor(selectStmt,
                                                               fetch_row_size)
            # Set the indicator to control a batch fetch for large tables
            if len(batch_values) > 0:
                data_available = True
            else:
                data_available = False
            
            ''' Set up a while loop to manage large source tables. This will
                set up a cursor to fetch a predetermined number of rows.'''
            while data_available == True:
                num_of_src_rows = len(batch_values)
                total_rows_read += num_of_src_rows

                #print('number of rows ', num_of_src_rows)               

                ''' If there are 0 rows then don't process or try to insert '''
                if num_of_src_rows > 0:
                    fmt_rows = []
                    for batch_row in batch_values:
                        fmt_row = replace_dt_columns(batch_row) #Format the datetimes

                        ''' Create a formatted row list for all row inserts
                            for bulk loading except the EmployeeEarnings
                            table, this needs to be managed with single inserts
                            to avoid an internal pyodbc binding error
                        '''
                        fmt_rows.append(fmt_row)
                        ''' The following statement will insert the row one
                            at a time '''
                        if table_name == 'EmployeeEarning':
                            QB_tgt_dbConn.insertRowWithValues(insertStmt,
                                                              fmt_row)

                    logging.info('Number of rows Selected -> {}'.format(
                                 num_of_src_rows))
                    # This manages the bulk load
                    if table_name != 'EmployeeEarning':
                        QB_tgt_dbConn.insertMultipleRows(insertStmt, fmt_rows)
                        logging.info('Multiple Insert Executed for -> {}'
                                     .format(table_name))

                ''' Check for the number of rows returned, if 0 or less than
                    the fetch size set the data available indicator to exit
                    the while loop '''
                if num_of_src_rows < fetch_row_size or num_of_src_rows == 0:
                    data_available = False
                else:
                    # select returns partial query results to manage large tables
                    batch_values = QB_src_dbConn.selectRowsWithCursorNextFetch(
                                                               fetch_row_size)

            ''' The following statement executes a SP which updates the
                encrypted column with the content of a raw data column 'xx'
                and then sets the raw column to NULL. This is for only the
                EmployeeEarning table
            '''
            if table_name == 'EmployeeEarning':
                QB_tgt_dbConn.executeSqlStmt("exec [PXLTD_CEDW].[dbo].SP_ENCRYPT_QB_SAL")    

            # Set up the body for the ETL Control End process
            body = {"Num_Rows_Read": total_rows_read,
                        "Num_Rows_Processed": total_rows_read,
                        "Total_Rows_From_Source": total_rows_read,
                        "Total_Rows_To_Target": total_rows_read
                        }

            # Call the ETL Control API
            end_response = etlControl.etlEndProcess(ETL_step_nm,'OK', body)

            if end_response['status'] == 'Fail':
                logging.info('End Process failed ->', end_response['result'])

            extract_end_time = time.time()
            logging.info('ETL Execution elapsed time -> %0.4f',
                         extract_end_time - extract_start_time)

        QB_tgt_dbConn.executeSqlStmt("exec [PXLTD_CEDW].[dbo].SP_QBAppend")
        logging.info('Executed the Stored Procedure SP_QBAppend')

        process_end_time = time.time()
        print('Total Elapsed Seconds -> ', process_end_time - process_start_time)

        logging.info('Number of Tables processed -> {}'.format(tables_processed+1))
        logging.info('Total Execution elapsed time -> %0.4f',
                     process_end_time - process_start_time)

        ''' Create and send the Success email '''
        msg_text = ('QuickBooks extract successful\n'
           'Extracted {} tables\n'
           'Execution time {:.4f} minutes'.format(tables_processed + 1,
                                (process_end_time - process_start_time)/60))
#        notifyEmailUsers('S', successEmailUsers, msg_text)
            
        logging.info('Execution ended. Error code is {}'.format(0))
        
 
    except Exception as err:
        logging.info('Error in QB Extract process - {}'.format(str(err)))
        
        ''' Create and send the Failure email '''
        msg_text = ('QuickBooks extract FAILED\nError {}'
                   '\nPlease Review log file {}'.format(str(err), log_file))
        notifyEmailUsers('F', successEmailUsers, msg_text)
            
        print('*** Process Failed ***')
        logging.info('Execution ended. Error code is {}'.format(1))

if __name__ == '__main__':
    main()
